// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { FairBindDesign2 } from "../FairBindDesign2.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { Rule8Store } from "./Rule8Store.sol";
import { Rule8Shared } from "./Rule8Shared.sol";

/// Extension module 9 (rule edition 8, v0.3): the anchor with the bulk
/// buyer-signature check and its binding proofs (rule D2-41), and the
/// release by state: release units, the per-seller cursor with its batch
/// payment and the separate release (rule D2-39), with the held count of
/// the cursor pass (rule D2-42).
contract FairBindRule8Release is Rule8Shared {
    uint8 public constant MODULE_KIND = 19;

    event BulkBound(uint32 indexed sellerId, uint24 indexed epoch, bytes32 bindRoot, uint32 bound, uint32 unbound);
    event BindingShown(bytes32 indexed nonce);
    event UnitReleased(uint32 indexed sellerId, uint24 indexed epoch, uint32 unit, uint32 selected, uint256 payAmount);
    event CursorPassed(uint32 indexed sellerId, uint24 indexed epoch, uint256 paid, uint256 levy, bool itemized);
    event SeparateRelease(bytes32 indexed nonce, uint32 indexed sellerId, uint256 value);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        Rule8Shared(token, gov, guard, treasury, rewardPool)
    { }

    // ------------------------------------- bulk signature check (revision 6)


    /// The seller-signed anchor of a receipt-signature profile with the bulk
    /// signature check (rule D2-41): anyone may submit it in the anchor
    /// window. In this transaction the contract checks, for every nonce,
    /// that it is a purchase of this seller epoch and that the buyer signed
    /// the bundle (65-byte low-s ecrecover against the settlement's payer;
    /// a smart-account payer binds by its earlier posting of the same
    /// bundle), sets beta_n, and computes three roots over the list: the
    /// anchor root over (nonce, leaf) that the cases read, root0 over
    /// lambda0_n = H(leaf || h_n) and R_e over lambda_n = H(leaf || h_n ||
    /// s_n), s_n the hash of the carried signature. The seller's signature
    /// covers (R_e, root0). It stores one slot, C_e = H(R_e || R^b_e), R^b_e
    /// the root over b_n = H(position || beta_n) in the same shape. A
    /// purchase with beta_n = 0 is no sale: it is marked for refund here,
    /// and the anchor does not revert for it (rule D2-41 (e)).
    function anchorBulk(
        Rule8Store.AnchorContent calldata c,
        Rule8Store.BulkEntry[] calldata entries,
        bytes calldata sellerSig
    ) external onlyDelegateCall nonReentrant {
        uint32 profileId = sellers[c.sellerId].viewData.profileId;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[profileId].bulkSig || _exchangeMode(profileId) == ExchangeStore.MODE_NONE) revert InvalidTransition();
        (AnchorView storage record, uint256 deadline) = _anchorChecks(c, profileId, entries.length);
        (bytes32 root, bytes32 root0, bytes32 rE, bytes32 rB, uint32 bound) = _bulkRoots(c, profileId, entries);
        if (root0 != c.root0 || rE != c.root || c.units != 1 || c.unitsHash != keccak256(abi.encode(rE, root0))) {
            revert InvalidProof();
        }
        bytes32 structHash = _anchorStructHash(c);
        if (!_sellerSigned(c.sellerId, profileId, structHash, sellerSig)) revert InvalidSignature();
        ExchangeStore.mark();
        Rule8Store.SellerEpoch storage se = r8.sellerEpochs[c.sellerId][c.epoch];
        se.content = structHash;
        se.bindRoot = keccak256(abi.encode(rE, rB));
        _finishAnchor(c.sellerId, c.epoch, record, profiles[profileId].parameters, deadline, root, c.publicationHash, c.count);
        emit BulkBound(c.sellerId, c.epoch, se.bindRoot, bound, c.count - bound);
        emit SignedAnchor(c.sellerId, c.epoch, msg.sender, structHash);
        _r8PayFee(profileId, msg.sender, r8.terms[profileId].cAnchor);
    }

    /// The checks an anchor shares with the seller's own (count, state, window).
    function _anchorChecks(Rule8Store.AnchorContent calldata c, uint32 profileId, uint256 n)
        private
        view
        returns (AnchorView storage record, uint256 deadline)
    {
        SellerView storage seller = sellers[c.sellerId].viewData;
        if (seller.status == uint8(SellerStatus.NONE) || seller.status == uint8(SellerStatus.EXITED)) {
            revert SellerInactive();
        }
        if (c.profileId != profileId) revert InvalidTransition();
        if (c.publicationHash == bytes32(0)) revert InvalidConfiguration();
        if (c.count == 0 || c.count != epochPurchaseCount[c.sellerId][c.epoch] || n != c.count) revert CountMismatch();
        record = anchors[c.sellerId][c.epoch];
        if (record.state != uint8(EpochState.NONE)) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint256 base = _anchorBase(profile, c.epoch);
        deadline = base + deadlineConfigs[profile.deadlineConfigId].anchorBlocks;
        if (block.number < base) revert AnchorTooEarly();
        if (block.number > deadline) revert AnchorWindowClosed();
    }

    function _bulkRoots(Rule8Store.AnchorContent calldata c, uint32 profileId, Rule8Store.BulkEntry[] calldata entries)
        private
        returns (bytes32 root, bytes32 root0, bytes32 rE, bytes32 rB, uint32 bound)
    {
        uint256 n = entries.length;
        bytes32[] memory l = new bytes32[](n);
        bytes32[] memory l0 = new bytes32[](n);
        bytes32[] memory le = new bytes32[](n);
        bytes32[] memory lb = new bytes32[](n);
        bytes32 domain = _exchangeDomain(profileId);
        address sellerKey = sellers[c.sellerId].viewData.signingKey;
        bytes32 prev;
        for (uint256 i; i < n; i++) {
            Rule8Store.BulkEntry calldata en = entries[i];
            bytes32 nonce = en.nonce;
            if (i != 0 && uint256(nonce) <= uint256(prev)) revert EntriesNotAscending();
            prev = nonce;
            bytes32 h = _bundleHash(en.ctHash, en.ekHash, en.rHash, en.leaf);
            bool beta = _bulkBeta(c, domain, sellerKey, en, h);
            if (beta) bound++;
            bytes32 s = en.sig.length == 0 ? bytes32(0) : keccak256(en.sig);
            l[i] = FairBindMerkle.entryHash(nonce, en.leaf);
            l0[i] = FairBindMerkle.entryHash(nonce, keccak256(abi.encode(en.leaf, h)));
            le[i] = FairBindMerkle.entryHash(nonce, keccak256(abi.encode(en.leaf, h, s)));
            lb[i] = FairBindMerkle.entryHash(nonce, keccak256(abi.encode(BIND_DOMAIN, i, beta)));
        }
        root = _fold(l);
        root0 = _fold(l0);
        rE = _fold(le);
        rB = _fold(lb);
    }

    /// beta_n of one entry; a purchase of this seller epoch that is not bound
    /// is marked for refund (rule D2-41 (d), D2-42 (a)).
    function _bulkBeta(
        Rule8Store.AnchorContent calldata c,
        bytes32 domain,
        address sellerKey,
        Rule8Store.BulkEntry calldata en,
        bytes32 h
    ) private returns (bool beta) {
        PurchaseView storage p = purchases[en.nonce];
        if (p.sellerId != c.sellerId || p.epoch != c.epoch || p.settledBlock == 0) return false;
        address payer = p.buyer;
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        if (payer.code.length != 0) {
            // A smart-account payer binds by its earlier posting (rule D2-41 (g)).
            beta = x.bundles[en.nonce] == h;
            if (beta) x.bundles[en.nonce] = bytes32(uint256(h) | 1);
        } else if (en.sig.length == 65) {
            bytes32 digest = keccak256(
                abi.encodePacked(
                    hex"1901",
                    domain,
                    keccak256(abi.encode(RECEIPT_SIGNATURE_TYPEHASH, sellerKey, en.nonce, en.ctHash, en.ekHash, en.rHash, en.leaf))
                )
            );
            bytes32 r;
            bytes32 s;
            uint8 v;
            bytes calldata sig = en.sig;
            assembly ("memory-safe") {
                r := calldataload(sig.offset)
                s := calldataload(add(sig.offset, 32))
                v := byte(0, calldataload(add(sig.offset, 64)))
            }
            if (uint256(s) <= SECP256K1_HALF_N && (v == 27 || v == 28)) {
                address got = ecrecover(digest, v, r, s);
                beta = got != address(0) && got == payer;
            }
        }
        if (beta) return true;
        uint8 fs = p.financialState;
        if ((fs == uint8(FinancialState.DEFERRED) || fs == uint8(FinancialState.RELEASABLE) || fs == uint8(FinancialState.HELD))
            && !_forfeitedEntry(p)) {
            _setFinancialState(en.nonce, FinancialState.REFUNDABLE);
            refundSources[en.nonce] = uint8(RefundSource.UNBOUND);
            x.records[en.nonce].early = true;
        }
    }

    /// The merkle-v1 root over level-zero hashes (an odd node pairs with itself).
    function _fold(bytes32[] memory level) private pure returns (bytes32) {
        uint256 width = level.length;
        if (width == 0) return bytes32(0);
        while (width > 1) {
            uint256 next = (width + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < width ? level[2 * i + 1] : left;
                level[i] = FairBindMerkle.nodeHash(left, right);
            }
            width = next;
        }
        return level[0];
    }

    /// Shows the binding of one purchase of a bulk-checked epoch (rule D2-41
    /// (c), (c′)): the inclusion of lambda_n in R_e and of b_n = H(position
    /// || 1) in R^b_e at the same position, against the stored C_e. It
    /// writes the purchase's bound mark, which the sample case, the dispute
    /// and the PASS proof read; an unsampled sale never needs it.
    function proveBinding(
        bytes32 nonce,
        Rule8Store.BulkEntry calldata en,
        bytes32 rE,
        bytes32 rB,
        uint32 position,
        bytes32[] calldata lambdaPath,
        bytes32[] calldata betaPath
    ) external onlyDelegateCall {
        PurchaseView storage p = purchases[nonce];
        if (p.settledBlock == 0 || en.nonce != nonce) revert InvalidTransition();
        Rule8Store.SellerEpoch storage se = Rule8Store.layout().sellerEpochs[p.sellerId][p.epoch];
        if (se.bindRoot == bytes32(0) || keccak256(abi.encode(rE, rB)) != se.bindRoot) revert InvalidProof();
        uint32 count = epochPurchaseCount[p.sellerId][p.epoch];
        bytes32 h = _bundleHash(en.ctHash, en.ekHash, en.rHash, en.leaf);
        bytes32 s = en.sig.length == 0 ? bytes32(0) : keccak256(en.sig);
        if (!FairBindMerkle.verify(rE, nonce, keccak256(abi.encode(en.leaf, h, s)), position, count, lambdaPath)) {
            revert InvalidProof();
        }
        if (!FairBindMerkle.verify(rB, nonce, keccak256(abi.encode(BIND_DOMAIN, uint256(position), true)), position, count, betaPath)) {
            revert InvalidProof();
        }
        ExchangeStore.layout().bundles[nonce] = bytes32(uint256(h) | 1);
        emit BindingShown(nonce);
    }

    // ----------------------------------- release by state (revision 4)


    /// The release unit call (rule D2-39 (n) 2): anyone may call it once the
    /// seller epoch is anchored and sealed and the buyer windows of its
    /// purchases closed, with the settlements of unit `unit` in settlement
    /// order. It checks (i) that the list recomputes the unit's accumulator
    /// and has the unit's length, and (ii) that every selected sale of the
    /// unit has its sample case at an end state; a selected purchase that is
    /// no sale (not bound by A_e) is not waited for. Then it marks the unit
    /// done and adds what the batch payment will pay. A purchase with an
    /// open dispute, or held by its case, is left for a separate release.
    /// Units may be done in any order; a wrong list reverts and leaves
    /// nothing. The caller is paid c_r0 + c_r1 * items (rule D2-38 (a)).
    function releaseUnit(uint32 sellerId, uint24 epoch, uint32 unit, Rule8Store.UnitItem[] calldata items)
        external
        onlyDelegateCall
        nonReentrant
    {
        uint32 profileId = sellers[sellerId].viewData.profileId;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        Rule8Store.Terms storage t = r8.terms[profileId];
        if (!t.on) revert InvalidTransition();
        Rule8Store.SellerEpoch storage se = r8.sellerEpochs[sellerId][epoch];
        if (se.passed) revert InvalidTransition();
        bytes32 randomness = _sealedValue(sellerId, epoch, profileId);
        if (block.number <= _buyerWindowEnd(profileId, epoch)) revert DeadlineNotReached();
        uint256 expected;
        {
            uint256 n = epochPurchaseCount[sellerId][epoch];
            uint256 size = uint256(1) << t.unitLog2;
            if (uint256(unit) * size >= n) revert InvalidTransition();
            uint256 left = n - uint256(unit) * size;
            expected = left < size ? left : size;
        }
        if (items.length != expected) revert CountMismatch();
        {
            uint256 word = r8.doneBits[sellerId][epoch][unit >> 8];
            if ((word >> (unit & 255)) & 1 == 1) revert InvalidTransition();
            r8.doneBits[sellerId][epoch][unit >> 8] = word | (uint256(1) << (unit & 255));
        }
        (uint256 acc, uint32 selected, uint256 pay, uint32 payCount, uint32 sep) =
            _scanUnit(sellerId, epoch, profileId, randomness, items);
        if (bytes32(acc) != r8.unitAcc[sellerId][epoch][unit]) revert InvalidProof();
        se.unitsDone++;
        se.selected += selected;
        se.payAmount += uint96(pay);
        se.payCount += payCount;
        se.separateCount += sep;
        uint256 fee = uint256(t.cR0) + uint256(t.cR1) * items.length;
        se.relFees += uint96(fee);
        emit UnitReleased(sellerId, epoch, unit, selected, pay);
        _r8PayFee(profileId, msg.sender, fee);
    }

    function _scanUnit(
        uint32 sellerId,
        uint24 epoch,
        uint32 profileId,
        bytes32 randomness,
        Rule8Store.UnitItem[] calldata items
    ) private returns (uint256 acc, uint32 selected, uint256 pay, uint32 payCount, uint32 sep) {
        bool tiered = profileTerms[profileId].tiers.length != 0;
        uint32 basePpm = profiles[profileId].parameters.samplePpm;
        bool signing = _exchangeMode(profileId) != ExchangeStore.MODE_NONE;
        bool bulk = Rule8Store.layout().sellerEpochs[sellerId][epoch].bindRoot != bytes32(0);
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        for (uint256 i; i < items.length; i++) {
            Rule8Store.UnitItem calldata it = items[i];
            bytes32 nonce = it.nonce;
            acc = uint256(keccak256(abi.encode(acc, nonce, it.payer, it.value, it.cap)));
            bool sale = !signing || (bulk ? refundSources[nonce] != uint8(RefundSource.UNBOUND) : _bound(nonce));
            if (sale && _selected(sellerId, epoch, nonce, randomness, tiered ? FairBindDesign2.samplePpm(it.value, it.cap) : basePpm, tiered)) {
                if (!_sampleEnded(nonce, signing)) revert NotSampled();
                selected++;
            }
            if (!sale) continue;
            uint8 fs = purchases[nonce].financialState;
            bool open = _disputeOpen(nonce);
            if ((fs == uint8(FinancialState.DEFERRED) || fs == uint8(FinancialState.RELEASABLE)) && !open) {
                pay += it.value;
                payCount++;
            } else if (fs == uint8(FinancialState.DEFERRED) || fs == uint8(FinancialState.RELEASABLE)
                || fs == uint8(FinancialState.HELD)) {
                r8.itemFlag[nonce] = Rule8Store.ITEM_SEPARATE;
                sep++;
            }
        }
    }

    /// The sampling value of an anchored seller epoch sealed by its profile
    /// epoch (rule D2-35 (b)); reverts otherwise.
    function _sealedValue(uint32 sellerId, uint24 epoch, uint32 profileId) private view returns (bytes32) {
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state == uint8(EpochState.SEALED)) return record.randomness;
        Rule8Store.ProfileEpoch storage pe = Rule8Store.layout().profileEpochs[profileId][epoch];
        if (record.state != uint8(EpochState.ANCHORED) || pe.state != Rule8Store.PE_SEALED) revert InvalidTransition();
        return pe.randomness;
    }

    /// The purchase is selected under the epoch's value, as _sampleStatus
    /// draws it.
    function _selected(uint32 sellerId, uint24 epoch, bytes32 nonce, bytes32 randomness, uint32 ppm, bool proportional)
        private
        pure
        returns (bool)
    {
        if (ppm >= PPM) return true;
        uint256 value = uint256(keccak256(abi.encode(SAMPLE_DOMAIN, randomness, sellerId, epoch, nonce)));
        return value < (proportional ? FairBindDesign2.threshold(ppm) : _probabilityThreshold(ppm));
    }

    /// The sample judgment of a selected sale is at an end state (rule D2-39
    /// (b) 2): its sample case ended (FINAL, INCONCLUSIVE, UNSERVED), or a
    /// dispute ended it as FAIL before it opened. A sample case that was not
    /// opened is not at an end state, and a purchase a non-delivery dispute
    /// refunded under receipt signatures still waits for its sample case.
    function _sampleEnded(bytes32 nonce, bool signing) private view returns (bool) {
        CaseView storage c = cases[nonce];
        uint8 s = c.state;
        if (s != uint8(CaseState.FINAL) && s != uint8(CaseState.INCONCLUSIVE) && s != uint8(CaseState.UNSERVED)) return false;
        if (c.trigger == uint8(CaseTrigger.SAMPLE)) return true;
        return !(signing && _refundedEarly(nonce));
    }

    /// A dispute or buyer recovery of the purchase is open.
    function _disputeOpen(bytes32 nonce) private view returns (bool) {
        if (_buyerRecoveryOpen(nonce)) return true;
        CaseView storage c = cases[nonce];
        uint8 s = c.state;
        if (s == uint8(CaseState.NONE) || c.trigger == uint8(CaseTrigger.SAMPLE)) return false;
        return s != uint8(CaseState.DELIVERED) && s != uint8(CaseState.UNSERVED) && s != uint8(CaseState.INCONCLUSIVE)
            && s != uint8(CaseState.FINAL);
    }

    /// The last block in which a buyer of the seller epoch may open a
    /// dispute: the epoch's last block plus the response and claim windows;
    /// for an unsigned account also W_e = M_e + w_b (rule D2-39 (b) 3).
    function _buyerWindowEnd(uint32 profileId, uint24 epoch) internal view returns (uint256 end) {
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        DeadlineConfig storage d = deadlineConfigs[profile.deadlineConfigId];
        end = uint256(_epochStart(profile, epoch + 1)) - 1 + d.responseBlocks + d.claimBlocks;
        if (_exchangeMode(profileId) == ExchangeStore.MODE_NONE) {
            uint256 w = uint256(_anchorDeadline(profile, epoch)) + 1 + _valueDelay(profile)
                + Rule8Store.layout().terms[profileId].buyerWindow;
            if (w > end) end = w;
        }
    }

    /// Moves the seller's release cursor over its next seller epoch E (rule
    /// D2-39 (b), (c)) when: E is over and (R1) anchored and sealed, or
    /// ended as EPOCH_FAILED (a missed anchor, a checkpoint shortage), (R2)
    /// every release unit of an anchored and sealed E is done, (R3) every
    /// buyer window of E is closed, and (R4) every earlier seller epoch was
    /// passed (the cursor moves in order). No pending initial FAIL of the
    /// account may wait. An anchored and sealed E pays the batch, less the
    /// levy, to the seller in one transfer; when a freeze of the account
    /// reaches into E, the batch is not paid and the purchases settled
    /// before the freeze are released one by one. The caller is paid the
    /// cursor fee.
    function passEpoch(uint32 sellerId) external onlyDelegateCall nonReentrant {
        SellerView storage seller = sellers[sellerId].viewData;
        uint32 profileId = seller.profileId;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        Rule8Store.Terms storage t = r8.terms[profileId];
        if (!t.on) revert InvalidTransition();
        uint24 e = r8.cursor[sellerId];
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        if (block.number < _epochStart(profile, e + 1)) revert DeadlineNotReached();
        Rule8Store.SellerEpoch storage se = r8.sellerEpochs[sellerId][e];
        uint256 n = epochPurchaseCount[sellerId][e];
        uint256 paid;
        uint256 levy;
        if (n != 0) {
            // A sealed profile epoch seals the anchored seller epoch; the
            // pass reads it without copying the value into the record.
            uint8 st = anchors[sellerId][e].state;
            if (st == uint8(EpochState.ANCHORED)) {
                if (r8.profileEpochs[profileId][e].state == Rule8Store.PE_SEALED) {
                    st = uint8(EpochState.SEALED);
                    _epochResolved(sellerId, e);
                } else {
                    st = _r8Materialize(sellerId, e);
                }
            }
            if (st != uint8(EpochState.SEALED) && st != uint8(EpochState.EPOCH_FAILED)) revert InvalidTransition();
            if (block.number <= _buyerWindowEnd(profileId, e)) revert DeadlineNotReached();
            uint32 bondId = seller.bondId;
            if (freezeTriggers[bondId].count != 0) revert FrozenEntry();
            levy = uint256(t.cEp) + se.relFees + r8.levyDebt[sellerId];
            if (st == uint8(EpochState.SEALED)) {
                uint256 size = uint256(1) << t.unitLog2;
                if (se.unitsDone != (n + size - 1) / size) revert NotSampled();
                levy += uint256(t.cAnchor) + uint256(t.cCase) * se.selected;
                if (_freezeReaches(bondId, profile, e)) {
                    se.itemized = true;
                    r8.levyDebt[sellerId] = levy;
                } else {
                    paid = _payBatch(sellerId, se, bondId, profileId, levy);
                }
            } else {
                r8.levyDebt[sellerId] = levy;
            }
            r8.openSellerEpochs[profileId][e]--;
            _heldOut(sellerId, profile, e, se, n);
        }
        se.passed = true;
        r8.cursor[sellerId] = e + 1;
        emit CursorPassed(sellerId, e, paid, levy, se.itemized);
        _fee(profileId, Rule8Store.FEE_CURSOR);
    }

    /// The cursor passed seller epoch E: every purchase of E still held and
    /// not left out for a separate release leaves the held count (paid in
    /// the batch, or refunded for an epoch that failed) (rule D2-42 (g)).
    function _heldOut(uint32 sellerId, ServiceProfileInput storage profile, uint24 e, Rule8Store.SellerEpoch storage se, uint256 n)
        private
    {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (uint256(_epochStart(profile, e + 1)) - 1 <= r8.episodeFloor[sellerId]) return;
        uint256 out = n - se.left - se.separateCount;
        uint32 held = r8.held[sellerId];
        r8.held[sellerId] = held > out ? uint32(held - out) : 0;
    }

    /// Pays the batch of a seller epoch: the levy (with earlier unpaid
    /// levies) goes to the fee pool first, the rest to the seller (rule
    /// D2-38 (b)). Returns the batch amount. A levy the batch does not cover
    /// stays as the seller's unpaid levy.
    function _payBatch(
        uint32 sellerId,
        Rule8Store.SellerEpoch storage se,
        uint32 bondId,
        uint32 profileId,
        uint256 levy
    ) private returns (uint256 amount) {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        amount = se.payAmount;
        se.paid = true;
        uint256 take = amount < levy ? amount : levy;
        r8.pool[profileId] += take;
        r8.levyDebt[sellerId] = levy - take;
        if (amount == 0) return 0;
        BondView storage b = bonds[bondId];
        b.deferredBalance -= amount;
        if (b.deferredBalance == 0) _deferredEmptied(bondId);
        if (amount > take) _transfer(sellers[sellerId].viewData.owner, amount - take);
    }

    /// Whether an open freeze of the account holds a settlement block of E.
    function _freezeReaches(uint32 bondId, ServiceProfileInput storage profile, uint24 e) private view returns (bool) {
        BondView storage b = bonds[bondId];
        if (b.freezeState != uint8(FreezeState.FROZEN) && b.freezeState != uint8(FreezeState.CLAIM_OPEN)) return false;
        FreezeSpan[] storage spans = freezeSpans[bondId];
        uint256 last = uint256(_epochStart(profile, e + 1)) - 1;
        uint256 first = _epochStart(profile, e);
        for (uint256 i; i < spans.length; i++) {
            if (spans[i].from <= last && spans[i].through >= first) return true;
        }
        return false;
    }

    /// Separate release (rule D2-39 (c), D2-29 (h)): a purchase left out of
    /// the batch of its seller epoch, or a purchase of an epoch whose batch a
    /// freeze stopped, is paid alone once the cursor passed its epoch, it is
    /// not frozen, and no case of it is open.
    function releaseSeparate(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[p.profileId].on) revert InvalidTransition();
        Rule8Store.SellerEpoch storage se = r8.sellerEpochs[p.sellerId][p.epoch];
        uint8 flag = r8.itemFlag[nonce];
        if (!se.passed || !(flag == Rule8Store.ITEM_SEPARATE || (se.itemized && flag == 0))) revert InvalidTransition();
        if (_frozen(p)) revert FrozenEntry();
        if (_disputeOpen(nonce)) revert InvalidTransition();
        uint8 cs = cases[nonce].state;
        if (cs != uint8(CaseState.NONE) && cs != uint8(CaseState.DELIVERED) && cs != uint8(CaseState.FINAL)
            && cs != uint8(CaseState.INCONCLUSIVE) && cs != uint8(CaseState.UNSERVED)) revert InvalidTransition();
        uint8 fs = p.financialState;
        if (fs != uint8(FinancialState.DEFERRED) && fs != uint8(FinancialState.RELEASABLE)) revert InvalidTransition();
        if (!_r8Sale(nonce, p.profileId, p.sellerId, p.epoch)) revert NotBound();
        r8.itemFlag[nonce] = Rule8Store.ITEM_DONE;
        _payDeposits(nonce);
        _setFinancialState(nonce, FinancialState.RELEASED);
        _transfer(sellers[p.sellerId].viewData.owner, p.value);
        emit SeparateRelease(nonce, p.sellerId, p.value);
    }

    function getSellerEpoch(uint32 sellerId, uint24 epoch)
        external
        view
        onlyDelegateCall
        returns (Rule8Store.SellerEpoch memory se, uint24 cursor, bytes32 acc0)
    {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        return (r8.sellerEpochs[sellerId][epoch], r8.cursor[sellerId], r8.unitAcc[sellerId][epoch][0]);
    }

    function getHeld(uint32 sellerId) external view onlyDelegateCall returns (uint32 held, uint64 episodeFloor) {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        return (r8.held[sellerId], r8.episodeFloor[sellerId]);
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](7);
        s[0] = this.anchorBulk.selector;
        s[1] = this.proveBinding.selector;
        s[2] = this.releaseUnit.selector;
        s[3] = this.passEpoch.selector;
        s[4] = this.releaseSeparate.selector;
        s[5] = this.getSellerEpoch.selector;
        s[6] = this.getHeld.selector;
    }

    function hookOps() external pure returns (uint256) {
        return 0;
    }
}
