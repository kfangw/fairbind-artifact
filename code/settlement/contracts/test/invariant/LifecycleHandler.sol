// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../../src/FairBind.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";
import { Inv } from "./InvariantBase.sol";
import { LifecycleObserver } from "./LifecycleObserver.sol";
import { ReceiptBook } from "./ReceiptBook.sol";

interface HandlerToken {
    function mint(address to, uint256 value) external;
    function approve(address spender, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// Fuzz target of the stateful suite. Two bond accounts: bond A carries two
/// seller registrations (more may be added), bond B one. Every action picks
/// an object in a state where it applies, moves the block forward to the
/// requested side of the relevant deadline (inside the window, exactly at the
/// deadline, or one block after it), calls the contract and compares the
/// outcome with the deadline rule. The block never moves backwards.
contract LifecycleHandler {

    // Branches counted for the coverage report.
    uint8 internal constant H_ANCHOR = 1;
    uint8 internal constant H_ANCHOR_LATE = 2;
    uint8 internal constant H_TIMEOUT_ANCHOR = 3;
    uint8 internal constant H_TIMEOUT_ANCHOR_EARLY = 4;
    uint8 internal constant H_SEAL = 5;
    uint8 internal constant H_SEAL_LATE = 6;
    uint8 internal constant H_TIMEOUT_SEAL = 7;
    uint8 internal constant H_SEAL_NO_HASH = 8;
    uint8 internal constant H_SEAL_EARLY = 9;
    uint8 internal constant H_JUDGE = 10;
    uint8 internal constant H_JUDGE_LATE = 11;
    uint8 internal constant H_TIMEOUT_JUDGE = 12;
    uint8 internal constant H_TIMEOUT_JUDGE_EARLY = 13;
    uint8 internal constant H_APPEAL = 14;
    uint8 internal constant H_APPEAL_LATE = 15;
    uint8 internal constant H_FINALIZE = 16;
    uint8 internal constant H_FINALIZE_EARLY = 17;
    uint8 internal constant H_SERVED = 18;
    uint8 internal constant H_SERVED_LATE = 19;
    uint8 internal constant H_TIMEOUT_SERVE = 20;
    uint8 internal constant H_TIMEOUT_SERVE_EARLY = 21;
    uint8 internal constant H_CLAIM = 22;
    uint8 internal constant H_CLAIM_LATE = 23;
    uint8 internal constant H_FORFEIT = 24;
    uint8 internal constant H_FORFEIT_EARLY = 25;
    uint8 internal constant H_REVIEW_SEAL = 26;
    uint8 internal constant H_REVIEW_EXPIRED = 27;
    uint8 internal constant H_AUTO_RECHECK = 28;
    uint8 internal constant H_EVIDENCE_TIMEOUT = 29;
    uint8 internal constant H_EVIDENCE_DISCLOSED = 30;
    uint8 internal constant H_RELEASE = 31;
    uint8 internal constant H_RELEASE_FROZEN = 32;
    uint8 internal constant H_REINSTATE = 33;
    uint8 internal constant H_KEEPER_SERVE = 34;
    uint8 internal constant H_BUYER_RECOVERY = 35;
    uint8 internal constant H_PUBLISH = 36;
    uint8 internal constant H_RATE_LIMIT = 37;
    uint8 internal constant H_EPOCH_CLAIM = 38;
    uint8 internal constant H_REFUND = 39;
    uint8 internal constant H_DISPUTE_LATE = 40;
    uint8 internal constant H_FREEZE_DEFERRED = 41;
    uint8 internal constant H_RELEASE_FROZEN_BOND = 42;
    uint8 internal constant H_CLAIM_FOREIGN = 43;
    uint8 internal constant H_SETTLE = 44;
    uint8 internal constant H_DISPUTE = 45;
    uint8 internal constant H_OPEN_SAMPLE = 46;
    uint8 internal constant H_REQUEST_SERVE = 47;
    uint8 internal constant H_ESCALATE = 48;
    uint8 internal constant H_REGISTER = 49;
    uint8 internal constant H_TOPUP = 50;
    uint8 internal constant H_RECOVERY_TIMEOUT = 51;
    uint8 internal constant H_CLAIM_EARLY_WINDOW = 52;
    uint8 internal constant H_REENTRY = 53;
    uint8 internal constant H_RESEAL = 54;
    uint8 internal constant H_RECEIPT_TIMEOUT = 55;
    uint8 internal constant H_DELIVERED_SAMPLE = 56;
    uint8 internal constant H_TERMS = 57;
    uint8 internal constant H_RECEIPT_SUBMIT = 58;
    // ADR 0028: an exhausted initial search of a sampled case waits; a redraw
    // after a newer checkpoint; a redraw refused before a newer checkpoint or
    // before its value; a release refused while the case waits.
    uint8 internal constant H_WAIT = 59;
    uint8 internal constant H_REDRAW = 60;
    uint8 internal constant H_REDRAW_EARLY = 61;
    uint8 internal constant H_RELEASE_WAITING = 62;
    // ADR 0029: a release refused only because the account's clock stopped
    // while one of its cases waited.
    uint8 internal constant H_RELEASE_PAUSED = 63;

    uint8 internal constant CS_SERVE_WAIT = uint8(FairBindCore.CaseState.SERVE_WAIT);
    uint8 internal constant CS_SERVE_CONFIRM = uint8(FairBindCore.CaseState.SERVE_CONFIRM);
    uint8 internal constant CS_PUBLISHING = uint8(FairBindCore.CaseState.PUBLISHING);
    uint8 internal constant CS_ASSIGNING = uint8(FairBindCore.CaseState.ASSIGNING);
    uint8 internal constant CS_JUDGING = uint8(FairBindCore.CaseState.JUDGING);
    uint8 internal constant CS_INITIAL = uint8(FairBindCore.CaseState.INITIAL_VERDICT);
    uint8 internal constant CS_PARTY = uint8(FairBindCore.CaseState.PARTY_REVIEW);
    uint8 internal constant CS_AUTO = uint8(FairBindCore.CaseState.AUTO_REVIEW);
    uint8 internal constant CS_TIEBREAK = uint8(FairBindCore.CaseState.TIEBREAK);
    uint8 internal constant CS_DELIVERED = uint8(FairBindCore.CaseState.DELIVERED);
    uint8 internal constant CS_UNSERVED = uint8(FairBindCore.CaseState.UNSERVED);
    uint8 internal constant CS_INCONCLUSIVE = uint8(FairBindCore.CaseState.INCONCLUSIVE);
    uint8 internal constant CS_FINAL = uint8(FairBindCore.CaseState.FINAL);
    uint8 internal constant CS_WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);
    uint8 internal constant F_DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);
    uint8 internal constant F_REFUNDABLE = uint8(FairBindCore.FinancialState.REFUNDABLE);
    uint8 internal constant F_REFUNDED = uint8(FairBindCore.FinancialState.REFUNDED);
    uint8 internal constant F_RELEASABLE = uint8(FairBindCore.FinancialState.RELEASABLE);
    uint8 internal constant F_RELEASED = uint8(FairBindCore.FinancialState.RELEASED);
    uint8 internal constant F_HELD = uint8(FairBindCore.FinancialState.HELD);
    uint8 internal constant T_NON_DELIVERY = uint8(FairBindCore.CaseTrigger.NON_DELIVERY);
    uint8 internal constant F_FORFEITED = uint8(FairBindCore.FinancialState.FORFEITED);
    uint8 internal constant E_NONE = uint8(FairBindCore.EpochState.NONE);
    uint8 internal constant E_ANCHORED = uint8(FairBindCore.EpochState.ANCHORED);
    uint8 internal constant E_SEALED = uint8(FairBindCore.EpochState.SEALED);
    uint8 internal constant E_FAILED = uint8(FairBindCore.EpochState.EPOCH_FAILED);
    uint8 internal constant Z_FROZEN = uint8(FairBindCore.FreezeState.FROZEN);
    uint8 internal constant Z_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);
    uint8 internal constant V_PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant V_FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant V_INCONCLUSIVE = uint8(FairBindCore.Verdict.INCONCLUSIVE);

    address internal constant OWNER_A = address(0x5E11A);
    address internal constant OWNER_B = address(0x5E11B);
    uint256 internal constant SELLER_KEY_BASE = 55_000;
    uint256 internal constant BUYER_KEY = 77_777;

    FairBind public immutable fb;
    HandlerToken public immutable token;
    LifecycleObserver public immutable obs;
    ReceiptBook public immutable book;
    address public immutable verifierOwner;
    address public immutable buyer;
    uint256 internal immutable penalty;
    /// The waiting-assignment variant (ADR 0028): verifiers start without
    /// room for one case and refillVerifiers writes newer checkpoints.
    bool internal immutable waitingSuite;

    uint256 public now_;
    uint128 internal nextKey = 1;
    uint256 internal extraSellers;
    uint8 internal kind;
    bytes32 internal subject;
    uint256 internal salt;
    uint256 internal busyEpoch = type(uint256).max;
    mapping(uint256 => bool) internal skipped;

    constructor(FairBind fairbind, address tokenAddress, address verifierOwnerAddress, bool freezeEnabled, bool waiting)
    {
        waitingSuite = waiting;
        fb = fairbind;
        token = HandlerToken(tokenAddress);
        verifierOwner = verifierOwnerAddress;
        obs = new LifecycleObserver(fairbind, tokenAddress, freezeEnabled);
        book = new ReceiptBook(fairbind, address(this));
        penalty = Inv.profile().sellerPenalty;
        buyer = Inv.vm.addr(BUYER_KEY);
        token.mint(buyer, 10_000_000_000);
        Inv.vm.prank(buyer);
        token.approve(address(fb), type(uint256).max);
        _fund(OWNER_A);
        _fund(OWNER_B);
        uint32 bondA = _openBond(OWNER_A, 2 * penalty);
        uint32 bondB = _openBond(OWNER_B, penalty);
        obs.addBond(bondA);
        obs.addBond(bondB);
        _register(bondA, OWNER_A);
        _register(bondA, OWNER_A);
        _register(bondB, OWNER_B);
        now_ = block.number;
    }

    /// Opens a bond account; under design 2 terms at CAP_HIGH in the base
    /// tier, whose unit bond is the profile's sellerPenalty (ADR 0024).
    function _openBond(address owner, uint256 amount) internal returns (uint32) {
        Inv.vm.prank(owner);
        if (Inv.tiered()) return fb.registerBondWithTerms(Inv.PROFILE, uint128(amount), Inv.CAP_HIGH, Inv.BASE_TIER);
        return fb.registerBond(Inv.PROFILE, uint128(amount));
    }

    /// Unit bond of the account now: sellerPenalty, or k * b(V*) under terms.
    function _unit(uint32 bondId) internal view returns (uint256) {
        return fb.unitBond(bondId);
    }

    function _fund(address owner) internal {
        token.mint(owner, 10_000_000_000);
        Inv.vm.prank(owner);
        token.approve(address(fb), type(uint256).max);
    }

    function _register(uint32 bondId, address owner) internal returns (bool ok) {
        uint256 key = SELLER_KEY_BASE + obs.sellerCount() + 1;
        address signer = Inv.vm.addr(key);
        Inv.vm.prank(owner);
        try fb.registerSeller(bondId, Inv.PROFILE, signer, Inv.CLAIMS) returns (uint32 sid) {
            ok = true;
            book.setSellerKey(sid, key);
            obs.addSeller(sid);
        } catch { }
    }

    // ---------------------------------------------------------------- helpers

    /// Restores the handler's block before an action reads block-dependent state.
    modifier synced() {
        Inv.vm.roll(now_);
        _;
    }

    function _begin(uint8 k, bytes32 s) internal {
        Inv.vm.roll(now_);
        kind = k;
        subject = s;
        obs.begin();
    }

    function _end() internal {
        now_ = block.number;
        obs.end(kind, subject);
    }

    /// Moves the block forward. On the way, a diligent seller anchors and a
    /// keeper seals every epoch whose window the move crosses; about one epoch
    /// in four is left to its seller's negligence, so the anchor and seal
    /// timeouts stay reachable. The epoch an explicit anchor or seal action
    /// works on is left alone.
    function _rollTo(uint256 target) internal {
        if (target <= block.number) return;
        // The release-clock model records waits that began or ended in this
        // block before the block moves (ADR 0029).
        obs.syncWaits();
        for (uint256 guard; guard < 32; guard++) {
            (uint256 at, uint256 ek, bool isSeal) = _nextDiligent(target);
            if (at == 0) break;
            if (at > block.number) Inv.vm.roll(at);
            _background(ek, isSeal);
        }
        if (target > block.number) Inv.vm.roll(target);
    }

    function _negligent(uint256 ek) internal view returns (bool) {
        return ek == busyEpoch || skipped[ek] || uint256(keccak256(abi.encode(ek, salt))) % 4 == 0;
    }

    function _nextDiligent(uint256 target) internal view returns (uint256 at, uint256 ek, bool isSeal) {
        uint256 len = obs.epochCount();
        for (uint256 i; i < len; i++) {
            uint256 k = obs.epochKeys(i);
            if (_negligent(k)) continue;
            FairBindCore.AnchorView memory a = fb.getAnchor(uint32(k >> 24), uint24(k));
            uint256 from;
            uint256 until;
            if (a.state == E_NONE) {
                from = 300 * (uint256(uint24(k)) + 2);
                until = from + Inv.ANCHOR_BLOCKS;
            } else if (a.state == E_ANCHORED) {
                from = uint256(a.randomBlock) + 1;
                until = a.sealDeadline;
            } else {
                continue;
            }
            if (until < block.number || from > target) continue;
            if (from < block.number) from = block.number;
            if (at == 0 || from < at) {
                at = from;
                ek = k;
                isSeal = a.state == E_ANCHORED;
            }
        }
    }

    function _background(uint256 ek, bool isSeal) internal {
        uint32 sid = uint32(ek >> 24);
        uint24 epoch = uint24(ek);
        if (isSeal) {
            _hash(fb.getAnchor(sid, epoch).randomBlock, ek);
            try fb.seal(sid, epoch) {
                obs.hit(H_SEAL);
            } catch (bytes memory err) {
                skipped[ek] = true;
                _flag(Inv.C_LIVENESS, "seal inside its window reverted", bytes32(ek), err);
            }
            return;
        }
        (, uint32 count) = book.build(sid, epoch);
        FairBindMerkle.ReceiptEntry[] memory entries = book.entries(sid, epoch);
        address owner = fb.getSeller(sid).owner;
        Inv.vm.prank(owner);
        try fb.anchor(sid, epoch, entries, count, keccak256("publication")) {
            obs.hit(H_ANCHOR);
        } catch (bytes memory err) {
            skipped[ek] = true;
            _flag(Inv.C_LIVENESS, "anchor inside its window reverted", bytes32(ek), err);
        }
    }

    function _flag(uint8 category, string memory what, bytes32 n, bytes memory err) internal {
        obs.flag(category, string.concat(what, " nonce ", Inv.hex32(n), " block ", Inv.toString(block.number),
            " error ", Inv.hex32(bytes32(Inv.selector(err)))));
    }

    /// Records a timed call: success outside the window is a safety violation
    /// of the given category, a revert inside it with every other
    /// precondition met is a liveness violation.
    function _timed(bool ok, bool inWindow, bool live, uint8 category, string memory what, bytes32 n, bytes memory err)
        internal
    {
        if (ok && !inWindow) _flag(category, string.concat(what, " succeeded outside its window"), n, err);
        if (!ok && inWindow && live) _flag(Inv.C_LIVENESS, string.concat(what, " reverted inside its window"), n, err);
    }

    function _hash(uint256 height, uint256 seed) internal {
        if (height < block.number && block.number - height <= 256) {
            Inv.vm.setBlockhash(height, keccak256(abi.encode("beacon", height, seed)));
        }
    }

    function _p(bytes32 n) internal view returns (FairBindCore.PurchaseView memory) {
        return fb.getPurchase(n);
    }

    function _c(bytes32 n) internal view returns (FairBindCore.CaseView memory) {
        return fb.getCase(n);
    }

    function _owner(bytes32 n) internal view returns (address) {
        return fb.getSeller(fb.getPurchase(n).sellerId).owner;
    }

    function _bondOf(bytes32 n) internal view returns (FairBindCore.BondView memory) {
        return fb.getBond(fb.getSeller(fb.getPurchase(n).sellerId).bondId);
    }

    function _find(uint256 seed, function(bytes32) internal view returns (bool) pred)
        internal
        view
        returns (bytes32)
    {
        uint256 len = obs.nonceCount();
        if (len == 0) return bytes32(0);
        uint256 start = seed % len;
        for (uint256 i; i < len; i++) {
            bytes32 n = obs.nonces((start + i) % len);
            if (pred(n)) return n;
        }
        return bytes32(0);
    }

    function _open(uint8 s) internal pure returns (bool) {
        return s != 0 && s != CS_DELIVERED && s != CS_UNSERVED && s != CS_INCONCLUSIVE && s != CS_FINAL;
    }

    function _done(uint8 s) internal pure returns (bool) {
        return s == CS_DELIVERED || s == CS_INCONCLUSIVE || s == CS_FINAL;
    }

    function _judgmentActive(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        return c.assignedVerifierId != 0
            && (c.state == CS_JUDGING || c.state == CS_PARTY || c.state == CS_AUTO || c.state == CS_TIEBREAK);
    }

    function _evidencePending(bytes32 n) internal view returns (bool) {
        if (_c(n).state != CS_INITIAL) return false;
        FairBindCore.AssignmentData[] memory list = fb.getAssignments(n);
        if (list.length == 0) return false;
        FairBindCore.AssignmentData memory a = list[list.length - 1];
        return a.evidenceRequested && !a.evidenceDisclosed;
    }

    /// Held from release: inside the frozen window, or any entry of a bond
    /// account with a pending initial FAIL (ADR 0021). The frozen window is
    /// the union of the spans of the open freeze, each from the settlement
    /// block of a failing sale (ADR 0030); entries settled before it keep
    /// their schedule. The window and the pending triggers are read from the
    /// observer's model (LifecycleObserver.heldByModel), not from the
    /// contract's spans, so that a freeze too wide or too narrow shows as a
    /// refused or a wrongful release.
    function _frozen(bytes32 n) internal view returns (bool) {
        FairBindCore.BondView memory b = _bondOf(n);
        return obs.pendingTriggers(b.bondId) != 0
            || ((b.freezeState == Z_FROZEN || b.freezeState == Z_OPEN) && obs.heldByModel(b.bondId, _p(n).settledBlock));
    }

    function _finalized(bytes32 n) internal view returns (bool) {
        uint8 st = _p(n).financialState;
        return st == F_REFUNDABLE || st == F_REFUNDED || st == F_RELEASED || fb.purchaseState(n) == F_FORFEITED;
    }

    function _recoveryOpen(bytes32 n) internal view returns (bool) {
        uint8 s = fb.getBuyerRecovery(n).state;
        return s == CS_SERVE_WAIT || s == CS_SERVE_CONFIRM || s == CS_PUBLISHING;
    }

    // ------------------------------------------------------------- settlement


    /// An open claim window admits settlements after a reinstatement reopened
    /// the account, from the block after freezeBlock (ADR 0021).
    function _settleExpected(uint32 sid) internal view returns (bool) {
        FairBindCore.SellerView memory s = fb.getSeller(sid);
        FairBindCore.BondView memory b = fb.getBond(s.bondId);
        bool reopened = b.freezeState == Z_OPEN && fb.getClaimReentry(s.bondId).reopened && block.number > b.freezeBlock;
        return s.status == uint8(FairBindCore.SellerStatus.ACTIVE) && b.status == uint8(FairBindCore.BondStatus.ACTIVE)
            && !b.sanctioned && b.balance >= _unit(s.bondId) && b.freezeState != Z_FROZEN && (b.freezeState != Z_OPEN || reopened)
            && obs.pendingTriggers(s.bondId) == 0 && obs.modelLevel(s.bondId) >= Inv.PPM;
    }

    /// Settles one to five purchases of one seller in one block.
    function settle(uint256 sellerSeed, uint256 valueSeed, uint256 countSeed) external synced {
        _begin(Inv.K_SETTLE, 0);
        if (salt == 0) salt = valueSeed | 1;
        _rollTo(block.number + (valueSeed >> 128) % 41);
        uint32 sid = obs.sellerIds(sellerSeed % obs.sellerCount());
        uint256 count = 1 + countSeed % 5;
        for (uint256 k; k < count; k++) _settleOne(sid, valueSeed, k);
        _end();
    }

    function _settleOne(uint32 sid, uint256 valueSeed, uint256 k) internal returns (bytes32 n, bool ok) {
        bool expected = _settleExpected(sid);
        bytes16 key = bytes16(nextKey++);
        bytes32 rh = book.requestHash(key);
        n = fb.deriveNonce(sid, Inv.PROFILE, Inv.CLAIMS, buyer, key, rh);
        // Under design 2 terms a purchase stays within the account's cap.
        uint256 cap = Inv.tiered() ? fb.getBondTerms(fb.getSeller(sid).bondId).sampleScaleValue : 10_000;
        uint256 value = 1 + uint256(keccak256(abi.encode(valueSeed, k))) % cap;
        FairBindCore.TransferAuthorization memory auth =
            FairBindCore.TransferAuthorization(buyer, address(fb), value, 0, type(uint64).max, n);
        try fb.settle(sid, Inv.PROFILE, Inv.CLAIMS, key, rh, auth, new bytes(65)) {
            ok = true;
            book.addPurchase(n, key);
            obs.recordSettle(n);
            obs.hit(H_SETTLE);
            if (fb.getBond(fb.getSeller(sid).bondId).freezeState == Z_OPEN) obs.hit(H_REENTRY);
            if (!expected) {
                _flag(Inv.C_STATUS, "settlement admitted for an inactive seller or frozen, sanctioned bond", n, "");
            }
        } catch (bytes memory err) {
            if (Inv.selector(err) == FairBindCore.RateLimitExceeded.selector) obs.hit(H_RATE_LIMIT);
            if (expected) _flag(Inv.C_LIVENESS, "settlement refused", n, err);
        }
    }

    /// Re-entry during an open claim window followed by a second confirmed
    /// failure (ADR 0021): tops up a bond account whose claim window is open,
    /// reinstates its suspended seller, settles one to three purchases, fails
    /// one of them through a non-delivery dispute, and in mode 0 releases the
    /// others once their release conditions hold. Each step is observed on its
    /// own. Without the moving freeze those releases pay the failing seller.
    /// When no seller is suspended in an open claim window, mode bit 1 first
    /// produces the confirmed failure that opens one: a purchase of an
    /// eligible seller fails through a judged dispute (_judgedFailure).
    function reenter(uint256 seed, uint8 mode) external synced {
        uint32 sid = _reentryCandidate(seed);
        if (sid == 0 && (mode >> 1) % 2 == 1) {
            uint32 first = _eligibleSeller(seed);
            if (first != 0) {
                bytes32[4] memory fs = _settleSealed(first, seed, 1);
                if (fs[0] != 0) _judgedFailure(fs[0], seed);
                sid = _reentryCandidate(seed);
            }
        }
        if (sid == 0) {
            _begin(Inv.K_OTHER, 0);
            _end();
            return;
        }
        uint32 bondId = fb.getSeller(sid).bondId;
        uint256 balance = fb.getBond(bondId).balance;
        if (balance < _unit(bondId)) {
            _begin(Inv.K_TOPUP, bytes32(uint256(bondId)));
            _topUp(bondId, _unit(bondId) - balance);
            _end();
        }
        _begin(Inv.K_REINSTATE, bytes32(uint256(sid)));
        _rollTo(uint256(fb.getBond(bondId).freezeBlock) + 1);
        _reinstate(sid);
        _end();
        bytes32[3] memory ns;
        uint256 count = 1 + (seed >> 32) % 3;
        _begin(Inv.K_SETTLE, 0);
        // A bucket clipped to zero below one penalty refills at the profile rate.
        _rollTo(block.number + 60);
        for (uint256 k; k < count; k++) (ns[k],) = _settleOne(sid, seed, k);
        _end();
        if (ns[0] == 0 || fb.getPurchase(ns[0]).nonce == 0) return;
        _begin(Inv.K_OTHER, ns[0]);
        _disputeNonDelivery(ns[0], 0);
        _end();
        if (_c(ns[0]).state != CS_SERVE_WAIT) return;
        _begin(Inv.K_OTHER, ns[0]);
        _timeoutServe(ns[0], 0);
        _end();
        if (mode % 2 != 0) return;
        for (uint256 k = 1; k < count; k++) {
            if (fb.getPurchase(ns[k]).nonce == 0) continue;
            _begin(Inv.K_RELEASE, ns[k]);
            _release(ns[k], 1);
            _end();
        }
    }

    function _reentryCandidate(uint256 seed) internal view returns (uint32) {
        uint256 len = obs.sellerCount();
        for (uint256 i; i < len; i++) {
            uint32 cand = obs.sellerIds((seed % len + i) % len);
            FairBindCore.SellerView memory sv = fb.getSeller(cand);
            FairBindCore.BondView memory bv = fb.getBond(sv.bondId);
            if (sv.status == uint8(FairBindCore.SellerStatus.SUSPENDED) && bv.freezeState == Z_OPEN && !bv.sanctioned
                && fb.getFreezeTriggers(sv.bondId).count == 0) {
                return cand;
            }
        }
        return 0;
    }

    /// An active seller that may settle and whose bond account is neither
    /// frozen nor in an open claim window, or zero.
    function _eligibleSeller(uint256 seed) internal view returns (uint32) {
        uint256 len = obs.sellerCount();
        for (uint256 i; i < len; i++) {
            uint32 cand = obs.sellerIds((seed % len + i) % len);
            uint8 z = fb.getBond(fb.getSeller(cand).bondId).freezeState;
            if (z != Z_FROZEN && z != Z_OPEN && _settleExpected(cand)) return cand;
        }
        return 0;
    }

    /// Settles `count` purchases of the seller in one block, then anchors and
    /// seals their epoch inside its windows. Each step is observed on its own.
    function _settleSealed(uint32 sid, uint256 seed, uint256 count) internal returns (bytes32[4] memory ns) {
        _begin(Inv.K_SETTLE, 0);
        for (uint256 k; k < count; k++) {
            (bytes32 n, bool ok) = _settleOne(sid, seed, k);
            if (ok) ns[k] = n;
        }
        _end();
        if (ns[0] == 0) return ns;
        uint24 epoch = _p(ns[0]).epoch;
        if (fb.getAnchor(sid, epoch).state == E_NONE) {
            _begin(Inv.K_OTHER, 0);
            _anchor(seed, 0, sid, epoch);
            _end();
        }
        if (fb.getAnchor(sid, epoch).state == E_ANCHORED) {
            _begin(Inv.K_OTHER, 0);
            _seal(seed, 0, sid, epoch);
            _end();
        }
    }

    /// Fails the purchase through a judged failure: a wrong-delivery dispute,
    /// an assignment, a FAIL verdict and the finalization after the appeal
    /// window. The judgment and review modules confirm it, which is where
    /// FreezeDisabled.sol removes the freeze (a serve timeout ends in the
    /// delivery module and freezes on that build too).
    function _judgedFailure(bytes32 n, uint256 seed) internal {
        _begin(Inv.K_OTHER, n);
        _disputeWrong(n, 0);
        _end();
        if (_c(n).state != CS_ASSIGNING) return;
        _begin(Inv.K_OTHER, n);
        _assign(n);
        _end();
        if (!_judgmentActive(n)) return;
        _begin(Inv.K_OTHER, n);
        _judge(n, 1, 0);
        _end();
        if (_c(n).state != CS_INITIAL) return;
        _begin(Inv.K_OTHER, n);
        _finalize(n, 0, seed);
        _end();
    }

    /// A confirmed failure followed by the release of purchases the seller
    /// made before it (inv. 18, the negative invariant of run.sh step 3):
    /// settles two to four purchases of an eligible seller, anchors and seals
    /// their epoch, fails the first through a judged failure, and releases
    /// the others once their release conditions hold. With the bond-level
    /// freeze the failure holds the others and every release is refused;
    /// without it (FreezeDisabled.sol) an unsampled one pays the failing
    /// seller principal settled before its failure.
    function failThenRelease(uint256 seed) external synced {
        uint32 sid = _eligibleSeller(seed);
        if (sid == 0) {
            _begin(Inv.K_OTHER, 0);
            _end();
            return;
        }
        uint256 count = 2 + (seed >> 32) % 3;
        bytes32[4] memory ns = _settleSealed(sid, seed, count);
        if (ns[0] == 0) return;
        _judgedFailure(ns[0], seed);
        for (uint256 k = 1; k < count; k++) {
            if (ns[k] == 0) continue;
            _begin(Inv.K_RELEASE, ns[k]);
            _release(ns[k], 1);
            _end();
        }
    }

    /// A sample case that waits for an assignment while entries of its
    /// account come due (ADR 0028, ADR 0029; run.sh steps 5 and 6): settles
    /// two to four purchases of an eligible seller, anchors and seals their
    /// epoch, and takes the first sampled one. Mode 0 opens its case now and
    /// releases the others once deferBlocks wall blocks have passed: the case
    /// still waits, so the release clock stopped and every release must be
    /// refused (PauseIgnored.sol releases them). Mode 1 opens its case only
    /// once its entry's other release conditions hold and releases that entry
    /// in the same block: the case waits, so the release must be refused
    /// (WaitRelease.sol releases it). In the variant whose verifiers have
    /// room the case is assigned at once and nothing waits.
    function waitThenRelease(uint256 seed, uint8 mode) external synced {
        uint32 sid = _eligibleSeller(seed);
        if (sid == 0) {
            _begin(Inv.K_OTHER, 0);
            _end();
            return;
        }
        uint256 count = 2 + (seed >> 32) % 3;
        bytes32[4] memory ns = _settleSealed(sid, seed, count);
        bytes32 s;
        for (uint256 k; k < count && s == 0; k++) {
            if (ns[k] != 0 && _sampleCandidate(ns[k])) s = ns[k];
        }
        if (s == 0) return;
        if (mode % 2 == 0) {
            _begin(Inv.K_OTHER, s);
            _openSample(s, false);
            _end();
            for (uint256 k; k < count; k++) {
                if (ns[k] == 0 || ns[k] == s) continue;
                _begin(Inv.K_RELEASE, ns[k]);
                _release(ns[k], 1);
                _end();
            }
            return;
        }
        FairBindCore.PurchaseView memory p = _p(s);
        FairBindCore.AnchorView memory a = fb.getAnchor(sid, p.epoch);
        uint256 target = uint256(p.claimUntil) + 1;
        uint256 releaseAt = uint256(p.releaseBlock) + obs.pausedSince(fb.getSeller(sid).bondId, p.settledBlock);
        if (releaseAt > target) target = releaseAt;
        if (p.retainUntil > target) target = p.retainUntil;
        if (uint256(a.sealDeadline) + Inv.OPEN_BLOCKS + 1 > target) target = uint256(a.sealDeadline) + Inv.OPEN_BLOCKS + 1;
        _begin(Inv.K_OTHER, s);
        _rollTo(target);
        if (_sampleCandidate(s)) _openSample(s, false);
        _end();
        _begin(Inv.K_RELEASE, s);
        _release(s, 0);
        _end();
    }

    function advance(uint256 seed) external synced {
        _begin(Inv.K_OTHER, 0);
        uint32[8] memory steps = [uint32(1), 37, 120, 301, 650, 1_900, 12_000, 41_000];
        _rollTo(block.number + steps[seed % 8]);
        _end();
    }

    // ------------------------------------------------------------------ keeper

    /// Like _find, but prefers a candidate for which live also holds.
    function _findLive(
        uint256 seed,
        function(bytes32) internal view returns (bool) pred,
        function(bytes32) internal view returns (bool) live
    ) internal view returns (bytes32 first) {
        uint256 len = obs.nonceCount();
        if (len == 0) return bytes32(0);
        uint256 start = seed % len;
        for (uint256 i; i < len; i++) {
            bytes32 n = obs.nonces((start + i) % len);
            if (!pred(n)) continue;
            if (live(n)) return n;
            if (first == 0) first = n;
        }
    }

    function _live(bytes32 n) internal view returns (bool) {
        uint8 s = fb.purchaseState(n);
        return s != F_REFUNDED && s != F_RELEASED && s != F_FORFEITED;
    }

    /// Advances one live purchase by the step its state calls for. Mode picks
    /// the side of the deadline: mostly timely, sometimes exactly at the
    /// deadline or one block after it.
    function _active(bytes32 n) internal view returns (bool) {
        uint8 s = _c(n).state;
        return _open(s) || _recoveryActive(n) || _p(n).financialState == F_REFUNDABLE;
    }

    /// Prefers a purchase with an open case three times in four.
    function _pickForKeeper(uint256 seed) internal view returns (bytes32 n) {
        if ((seed >> 240) % 4 != 0) n = _find(seed, _active);
        if (n == 0) n = _find(seed, _live);
    }

    function keeper(uint256 seed, uint8 mode) external synced {
        bytes32 n = _pickForKeeper(seed);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _keep(n, mode, seed);
        _end();
    }

    /// Two to six keeper steps on one purchase, each observed on its own, so
    /// that one case can travel far along its path in a single call.
    function keeperRun(uint256 seed, uint8 mode) external synced {
        bytes32 n = _pickForKeeper(seed);
        for (uint256 i; i < 2 + mode % 5; i++) {
            uint256 s = uint256(keccak256(abi.encode(seed, i)));
            _begin(Inv.K_OTHER, n);
            if (n != 0 && _live(n)) _keep(n, uint8(s >> 100), s);
            _end();
        }
    }

    function _keep(bytes32 n, uint8 mode, uint256 seed) internal {
        uint8 r = mode % 10;
        uint8 side = r < 7 ? 0 : r == 7 ? 1 : 2;
        FairBindCore.PurchaseView memory p = _p(n);
        FairBindCore.CaseView memory c = _c(n);
        FairBindCore.BondView memory b = _bondOf(n);
        uint32 bondId = fb.getSeller(p.sellerId).bondId;
        uint8 epochState = fb.getAnchor(p.sellerId, p.epoch).state;
        uint8 s = c.state;
        if (_recoveryActive(n)) {
            _buyerRecovery(n, side);
        } else if (p.financialState == F_REFUNDABLE) {
            _claimRefund(n);
        } else if (b.freezeState == Z_OPEN && _frozenClaimable(n) && r < 8) {
            if (r < 5) _claimFrozen(n, side);
            else _forfeit(bondId, 0);
        } else if (b.freezeState == Z_FROZEN && r == 9) {
            _releaseFrozen(bondId);
        } else if (s == CS_ASSIGNING && epochState == E_SEALED) {
            _assign(n);
        } else if (s == CS_WAITING) {
            if (r == 9) _release(n, 1);
            else if (r == 8) _refill(seed);
            else _redraw(n, r, seed);
        } else if (_judgmentActive(n)) {
            if (r < 6) _judge(n, uint8(seed >> 40), 0);
            else if (r == 6) _requestServe(n);
            else if (r == 7) _judge(n, uint8(seed >> 40), 1);
            else _timeoutJudge(n, r == 8 ? 0 : 1);
        } else if (s == CS_INITIAL) {
            _keepInitial(n, r, side, seed);
        } else if (_reviewWaiting(n)) {
            _sealReview(n, r < 7 ? 0 : r == 7 ? 2 : r == 8 ? 3 : 1, seed);
        } else if (s == CS_SERVE_WAIT) {
            if (r < 6) _served(n, side);
            else _timeoutServe(n, r == 9 ? 1 : 0);
        } else if (s == CS_SERVE_CONFIRM) {
            _confirmServe(n, r < 3 ? 0 : r < 5 ? 1 : r == 9 ? 2 : 3);
        } else if (s == CS_PUBLISHING) {
            if (r < 6) _publish(n);
            else _timeoutServe(n, r == 9 ? 1 : 0);
        } else if (epochState == E_NONE) {
            if (s == 0 && r < 3 && block.number <= p.claimUntil) _disputeWrong(n, side);
            else if (s == 0 && r == 3) _disputeNonDelivery(n, side);
            else _anchor(seed, r < 7 ? 0 : r == 7 ? 1 : r == 8 ? 2 : 3, p.sellerId, p.epoch);
        } else if (epochState == E_ANCHORED) {
            _seal(seed, r < 6 ? 0 : r == 6 ? 4 : r == 7 ? 1 : r == 8 ? 2 : 3, p.sellerId, p.epoch);
        } else if (epochState == E_FAILED) {
            if (!_finalized(n)) _claimEpochFailure(n);
        } else if (s == 0) {
            _keepUnopened(n, r, side, p.claimUntil);
        } else if (s == CS_DELIVERED && r >= 2 && _sampleCandidate(n)) {
            _openSample(n, false);
        } else if (s == CS_DELIVERED && r < 2 && block.number <= p.claimUntil) {
            _disputeWrong(n, 0);
        } else if (_done(s) || s == CS_UNSERVED) {
            _release(n, r < 8 ? 1 : 0);
        }
    }

    function _keepInitial(bytes32 n, uint8 r, uint8 side, uint256 seed) internal {
        uint8 iv = _c(n).initialVerdict;
        if (_evidencePending(n)) {
            if (r < 6) _disclose(n, side);
            else _timeoutEvidence(n, r == 9 ? 1 : 0);
        } else if (r < 2) {
            _appeal(n, side);
        } else if (r == 2 && _evidenceRequestable(n)) {
            _requestEvidence(n, seed % 2 == 0, 0);
        } else if (r == 3 && iv == V_FAIL) {
            _freezeDeferred(n);
        } else if (iv != V_FAIL && r < 8) {
            _openAutoRecheck(n, r == 7 ? 2 : 0, seed);
        } else {
            _finalize(n, r == 9 ? 1 : 0, seed);
        }
    }

    function _keepUnopened(bytes32 n, uint8 r, uint8 side, uint64 claimUntil) internal {
        (bool sampled,) = fb.isSampled(n);
        if (sampled) _openSample(n, false);
        else if (r < 4 && block.number <= claimUntil) _disputeWrong(n, side);
        else if (r == 4 && block.number <= claimUntil) _disputeNonDelivery(n, 0);
        else if (r >= 8) _release(n, 1);
    }

    // ------------------------------------------------------ anchoring, sealing

    function _findEpoch(uint256 seed, uint8 state) internal view returns (bool found, uint32 sid, uint24 epoch) {
        uint256 len = obs.epochCount();
        if (len == 0) return (false, 0, 0);
        // Prefer an epoch whose window is still open.
        for (uint256 pass; pass < 2; pass++) {
            for (uint256 i; i < len; i++) {
                uint256 ek = obs.epochKeys((seed % len + i) % len);
                sid = uint32(ek >> 24);
                epoch = uint24(ek);
                FairBindCore.AnchorView memory a = fb.getAnchor(sid, epoch);
                if (a.state != state) continue;
                uint256 due = state == E_NONE ? 300 * (uint256(epoch) + 2) + Inv.ANCHOR_BLOCKS : a.sealDeadline;
                if (pass == 1 || block.number <= due) return (true, sid, epoch);
            }
        }
        return (false, 0, 0);
    }

    function anchorEpoch(uint256 seed, uint8 mode) external synced {
        _begin(Inv.K_OTHER, 0);
        (bool found, uint32 sid, uint24 epoch) = _findEpoch(seed, E_NONE);
        if (found) _anchor(seed, mode % 4, sid, epoch);
        _end();
    }

    /// Mode 0 inside the window, 1 at the deadline, 2 one block after it
    /// (then timeoutAnchor), 3 timeoutAnchor at the deadline.
    function _anchor(uint256 seed, uint8 m, uint32 sid, uint24 epoch) internal {
        uint256 base = 300 * (uint256(epoch) + 2);
        uint256 deadline = base + Inv.ANCHOR_BLOCKS;
        busyEpoch = (uint256(sid) << 24) | epoch;
        _rollTo(m == 0 ? base + (seed >> 64) % 8 : m == 2 ? deadline + 1 : deadline);
        busyEpoch = type(uint256).max;
        bytes32 tag = bytes32((uint256(sid) << 24) | epoch);
        if (m == 3) {
            try fb.timeoutAnchor(sid, epoch) {
                _timed(true, block.number > deadline, true, Inv.C_DEADLINE, "timeoutAnchor", tag, "");
                obs.hit(H_TIMEOUT_ANCHOR);
            } catch (bytes memory err) {
                _timed(false, block.number > deadline, true, Inv.C_DEADLINE, "timeoutAnchor", tag, err);
                obs.hit(H_TIMEOUT_ANCHOR_EARLY);
            }
            return;
        }
        (, uint32 count) = book.build(sid, epoch);
        FairBindMerkle.ReceiptEntry[] memory entries = book.entries(sid, epoch);
        address owner = fb.getSeller(sid).owner;
        bool inWindow = block.number >= base && block.number <= deadline;
        Inv.vm.prank(owner);
        try fb.anchor(sid, epoch, entries, count, keccak256("publication")) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "anchor", tag, "");
            obs.hit(H_ANCHOR);
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "anchor", tag, err);
            if (block.number > deadline) {
                obs.hit(H_ANCHOR_LATE);
                try fb.timeoutAnchor(sid, epoch) {
                    obs.hit(H_TIMEOUT_ANCHOR);
                } catch (bytes memory err2) {
                    _flag(Inv.C_LIVENESS, "timeoutAnchor after the deadline reverted", tag, err2);
                }
            }
        }
    }

    function sealEpoch(uint256 seed, uint8 mode) external synced {
        _begin(Inv.K_OTHER, 0);
        (bool found, uint32 sid, uint24 epoch) = _findEpoch(seed, E_ANCHORED);
        if (found) _seal(seed, mode % 6, sid, epoch);
        _end();
    }

    /// True when the checkpoint of the epoch, the latest written at or before
    /// its anchor deadline, is missing or holds fewer than minVerifiers
    /// verifiers: the one case in which an anchored epoch may end without its
    /// value (rule D2-16 (f), ADR 0029).
    function _shortCheckpoint(FairBindCore.AnchorView memory a) internal view returns (bool) {
        uint256 deadline = uint256(a.randomBlock) - 1 - Inv.profile().beaconDelayBlocks;
        uint64 last;
        for (uint64 v = 1;; v++) {
            (uint64 stored, uint64 cpBlock) = _checkpointBlock(v);
            if (stored == 0 || cpBlock > deadline) break;
            last = v;
        }
        if (last == 0) return true;
        (, uint32[] memory ids,,,) = fb.getVerifierCheckpoint(Inv.PROFILE, last);
        return ids.length < Inv.profile().minVerifiers;
    }

    /// Mode 0 inside the window, 1 at the deadline, 2 one block after it, 3 at
    /// the beacon block (too early), 4 inside the window with no value (block
    /// hash zero), 5 after the chain stopped serving the value. Under rule
    /// D2-16 (ADR 0029) seal succeeds whenever the value is served after the
    /// beacon block, also after sealDeadline; without it the epoch stays
    /// ANCHORED. timeoutSeal succeeds only on a short checkpoint, never on the
    /// suite's fourteen verifiers.
    function _seal(uint256 seed, uint8 m, uint32 sid, uint24 epoch) internal {
        FairBindCore.AnchorView memory a = fb.getAnchor(sid, epoch);
        uint256 rb = a.randomBlock;
        uint256 sd = a.sealDeadline;
        busyEpoch = (uint256(sid) << 24) | epoch;
        _rollTo(m == 0 || m == 4 ? rb + 1 + (seed >> 64) % 8 : m == 1 ? sd : m == 2 ? sd + 1 : m == 5 ? rb + 257 : rb);
        busyEpoch = type(uint256).max;
        if (m == 4 && block.number > rb) Inv.vm.setBlockhash(rb, bytes32(0));
        else _hash(rb, seed);
        bytes32 tag = bytes32((uint256(sid) << 24) | epoch);
        bool valued = block.number > rb && block.number - rb <= 256 && m != 4;
        try fb.seal(sid, epoch) {
            _timed(true, valued, true, Inv.C_DEADLINE, "seal", tag, "");
            if (fb.getAnchor(sid, epoch).state != E_SEALED) _flag(Inv.C_CASE, "seal did not seal", tag, "");
            obs.hit(H_SEAL);
            if (block.number > sd) obs.hit(H_SEAL_LATE);
        } catch (bytes memory err) {
            _timed(false, valued, true, Inv.C_DEADLINE, "seal", tag, err);
            if (block.number <= rb) obs.hit(H_SEAL_EARLY);
            else if (!valued) obs.hit(H_SEAL_NO_HASH);
            if (fb.getAnchor(sid, epoch).state != E_ANCHORED) _flag(Inv.C_CASE, "seal without its value ended the epoch", tag, "");
        }
        if (fb.getAnchor(sid, epoch).state != E_ANCHORED) return;
        bool shortage = block.number > rb - 1 - Inv.profile().beaconDelayBlocks && _shortCheckpoint(a);
        try fb.timeoutSeal(sid, epoch) {
            _timed(true, shortage, true, Inv.C_DEADLINE, "timeoutSeal", tag, "");
        } catch (bytes memory err) {
            _timed(false, shortage, true, Inv.C_DEADLINE, "timeoutSeal", tag, err);
            obs.hit(H_TIMEOUT_SEAL);
        }
    }

    // ---------------------------------------------------------- case opening

    /// A sampled purchase without a case, or whose non-delivery dispute ended
    /// as delivered (ADR 0024).
    function _sampleCandidate(bytes32 n) internal view returns (bool) {
        FairBindCore.PurchaseView memory p = _p(n);
        (bool eligible, bool known) = fb.isSampled(n);
        return known && eligible && (_c(n).state == 0 && p.financialState == F_DEFERRED || _deliveredDispute(n))
            && fb.purchaseState(n) != F_FORFEITED;
    }

    function _deliveredDispute(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        uint8 st = _p(n).financialState;
        return c.state == CS_DELIVERED && c.trigger == T_NON_DELIVERY && (st == F_RELEASABLE || st == F_HELD);
    }

    function _unsampledCandidate(bytes32 n) internal view returns (bool) {
        (bool eligible, bool known) = fb.isSampled(n);
        return known && !eligible && _c(n).state == 0;
    }

    function openSample(uint256 seed, bool unsampled) external synced {
        bytes32 n = _find(seed, unsampled ? _unsampledCandidate : _sampleCandidate);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _openSample(n, unsampled);
        _end();
    }

    function _openSample(bytes32 n, bool unsampled) internal {
        bool delivered = _deliveredDispute(n);
        try fb.openSample(n) {
            obs.hit(H_OPEN_SAMPLE);
            if (delivered) obs.hit(H_DELIVERED_SAMPLE);
            if (unsampled) _flag(Inv.C_CASE, "openSample opened an unsampled purchase", n, "");
            if (_c(n).requesterRole == 3) obs.hit(H_KEEPER_SERVE);
            _noteWait(n);
        } catch (bytes memory err) {
            if (!unsampled && _sampleCandidate(n)) _flag(Inv.C_LIVENESS, "openSample of a sampled purchase reverted", n, err);
        }
    }

    function _disputable(bytes32 n) internal view returns (bool) {
        uint8 s = _c(n).state;
        return (s == 0 || s == CS_DELIVERED) && !_finalized(n);
    }

    function _claimOpen(bytes32 n) internal view returns (bool) {
        return block.number <= _p(n).claimUntil;
    }

    function disputeWrongDelivery(uint256 seed, uint8 mode) external synced {
        bytes32 n = _findLive(seed, _disputable, _claimOpen);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _disputeWrong(n, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at claimUntil, 2 one block after it.
    function _disputeWrong(bytes32 n, uint8 m) internal {
        FairBindCore.PurchaseView memory p = _p(n);
        _rollTo(m == 0 ? 0 : m == 1 ? p.claimUntil : uint256(p.claimUntil) + 1);
        (FairBindCore.FairBindReceipt memory r, bytes memory sig) = book.signedReceipt(n);
        uint8 s = _c(n).state;
        bool live = (s == 0 && p.financialState == F_DEFERRED) || (s == CS_DELIVERED && !_recoveryOpen(n));
        bool inWindow = block.number <= p.claimUntil;
        Inv.vm.prank(buyer);
        try fb.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, sig) {
            _timed(true, inWindow, live, Inv.C_DEADLINE, "dispute(WRONG_DELIVERY)", n, "");
            obs.hit(H_DISPUTE);
        } catch (bytes memory err) {
            _timed(false, inWindow, live, Inv.C_DEADLINE, "dispute(WRONG_DELIVERY)", n, err);
            if (!inWindow) obs.hit(H_DISPUTE_LATE);
        }
    }

    function _nonDeliveryCandidate(bytes32 n) internal view returns (bool) {
        return !_finalized(n) && (_c(n).state == 0 || fb.getBuyerRecovery(n).state == 0);
    }

    function disputeNonDelivery(uint256 seed, uint8 mode) external synced {
        bytes32 n = _findLive(seed, _nonDeliveryCandidate, _claimOpen);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _disputeNonDelivery(n, mode % 4);
        _end();
    }

    /// Mode 0 after responseDue, 1 at claimUntil, 2 one block after it, 3 at
    /// responseDue (too early).
    function _disputeNonDelivery(bytes32 n, uint8 m) internal {
        FairBindCore.PurchaseView memory p = _p(n);
        _rollTo(m == 0 ? uint256(p.responseDue) + 1 : m == 1 ? p.claimUntil : m == 2 ? uint256(p.claimUntil) + 1
            : p.responseDue);
        FairBindCore.FairBindReceipt memory empty;
        bool fresh = _c(n).state == 0;
        bool live = fresh && p.financialState == F_DEFERRED;
        bool inWindow = block.number > p.responseDue && block.number <= p.claimUntil;
        Inv.vm.prank(buyer);
        try fb.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "") {
            _timed(true, inWindow, live, Inv.C_DEADLINE, "dispute(NON_DELIVERY)", n, "");
            obs.hit(fresh ? H_DISPUTE : H_BUYER_RECOVERY);
        } catch (bytes memory err) {
            _timed(false, inWindow, live, Inv.C_DEADLINE, "dispute(NON_DELIVERY)", n, err);
            if (block.number > p.claimUntil) obs.hit(H_DISPUTE_LATE);
        }
    }

    function _assigning(bytes32 n) internal view returns (bool) {
        return _c(n).state == CS_ASSIGNING;
    }

    function assignVerifier(uint256 seed) external synced {
        bytes32 n = _find(seed, _assigning);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _assign(n);
        _end();
    }

    function _assign(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = _p(n);
        bool sealed_ = fb.getAnchor(p.sellerId, p.epoch).state == E_SEALED;
        try fb.assignVerifier(n) {
            if (!sealed_) _flag(Inv.C_CASE, "verifier assigned before the epoch was sealed", n, "");
            if (_c(n).requesterRole == 3 && _c(n).state == CS_PUBLISHING) obs.hit(H_KEEPER_SERVE);
            _noteWait(n);
        } catch (bytes memory err) {
            if (sealed_) _flag(Inv.C_LIVENESS, "assignVerifier on a sealed epoch reverted", n, err);
        }
    }

    /// Records a case that entered WAITING_ASSIGNMENT and checks that only the
    /// initial stage of a sampled case waits (ADR 0028).
    function _noteWait(bytes32 n) internal {
        FairBindCore.CaseView memory c = _c(n);
        if (c.state != CS_WAITING) return;
        obs.hit(H_WAIT);
        if (c.trigger != uint8(FairBindCore.CaseTrigger.SAMPLE) || c.stage != uint8(FairBindCore.JudgmentStage.INITIAL)) {
            _flag(Inv.C_CASE, "a case other than the initial stage of a sample case waits", n, "");
        }
        if (_p(n).financialState != F_HELD) _flag(Inv.C_CASE, "waiting case left its purchase unheld", n, "");
    }

    function _waiting(bytes32 n) internal view returns (bool) {
        return _c(n).state == CS_WAITING;
    }

    function redraw(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _waiting);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _redraw(n, mode % 8, seed);
        _end();
    }

    /// Returns the first checkpoint written in a block after the case's last
    /// search, or zero.
    function _nextCheckpoint(bytes32 n) internal view returns (uint64 version, uint64 at) {
        FairBindCore.AssignmentWait memory w = fb.getAssignmentWait(n);
        for (uint64 v = w.checkpointVersion + 1;; v++) {
            (uint64 stored, uint64 cpBlock) = _checkpointBlock(v);
            if (stored == 0) return (0, 0);
            if (cpBlock > w.searchBlock) return (v, cpBlock);
        }
    }

    /// Block of checkpoint version v, and v itself, or zeros when v does not exist.
    function _checkpointBlock(uint64 v) internal view returns (uint64 stored, uint64 cpBlock) {
        (cpBlock,,,,) = fb.getVerifierCheckpoint(Inv.PROFILE, v);
        if (cpBlock != 0) stored = v;
    }

    /// Redraws a waiting case. Mode 0 to 4 at the first block its value
    /// exists (the newer checkpoint's block plus beaconDelayBlocks + 1), mode
    /// 5 to 7 now. Without a newer checkpoint, or before the value, the call
    /// must revert; after it, it must not, it keeps the attempt and an
    /// assignment starts its judgment deadline in that block (ADR 0028).
    function _redraw(bytes32 n, uint8 m, uint256 seed) internal {
        (uint64 v, uint64 cpBlock) = _nextCheckpoint(n);
        uint256 rb = uint256(cpBlock) + 1 + Inv.profile().beaconDelayBlocks;
        if (v != 0 && m < 5) {
            _rollTo(rb + 1);
            _hash(rb, seed);
        }
        // The cheatcode reads the block after the roll; under via_ir a cached
        // block.number could be stale within this function.
        uint256 current = Inv.vm.getBlockNumber();
        bool due = v != 0 && current > rb;
        uint8 attempt = _c(n).attempt;
        try fb.assignVerifier(n) {
            if (!due) _flag(Inv.C_CASE, "redraw without a newer checkpoint or before its value", n, "");
            FairBindCore.CaseView memory c = _c(n);
            if (c.attempt != attempt) _flag(Inv.C_CASE, "redraw consumed an assignment", n, "");
            if (c.state == CS_JUDGING) {
                obs.hit(H_REDRAW);
                if (c.judgeDue != current + Inv.JUDGE_BLOCKS) {
                    _flag(Inv.C_CASE, "redraw did not start the judgment deadline at the assignment", n, "");
                }
                if (fb.getAssignmentWait(n).checkpointVersion != v) {
                    _flag(Inv.C_CASE, "redraw used another checkpoint than the first one after the search", n, "");
                }
            } else if (c.state == CS_WAITING) {
                obs.hit(H_WAIT);
            } else {
                _flag(Inv.C_CASE, "redraw left the case neither judging nor waiting", n, "");
            }
        } catch (bytes memory err) {
            if (due) _flag(Inv.C_LIVENESS, "redraw after a newer checkpoint and its value reverted", n, err);
            else obs.hit(H_REDRAW_EARLY);
        }
    }

    function refillVerifiers(uint256 seed) external synced {
        _begin(Inv.K_OTHER, 0);
        _refill(seed);
        _end();
    }

    /// Waiting variant only: the verifier owner tops up about half of the
    /// verifiers by one case of room and writes a checkpoint one block later,
    /// when every verifier of the suite is still eligible for one.
    function _refill(uint256 seed) internal {
        if (!waitingSuite) return;
        uint256 p = Inv.profile().minVerifierBond;
        for (uint32 id = 1; id <= Inv.VERIFIER_COUNT; id++) {
            FairBindCore.VerifierView memory v = fb.getVerifier(id);
            if (v.status != uint8(FairBindCore.VerifierStatus.ACTIVE) || v.bond < p) return;
        }
        for (uint32 id = 1; id <= Inv.VERIFIER_COUNT; id++) {
            if ((seed >> id) & 1 == 0) continue;
            Inv.vm.prank(verifierOwner);
            fb.topUpVerifierBond(id, uint128(Inv.WAIT_TOP_UP));
        }
        _rollTo(block.number + 1);
        fb.checkpointVerifierTree(Inv.PROFILE);
    }

    // -------------------------------------------------------------- judgment

    function _judgeOpen(bytes32 n) internal view returns (bool) {
        return block.number <= _c(n).judgeDue;
    }

    function judge(uint256 seed, uint8 verdictSeed, uint8 mode) external synced {
        bytes32 n = _findLive(seed, _judgmentActive, _judgeOpen);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _judge(n, verdictSeed, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at judgeDue, 2 one block after it.
    function _judge(bytes32 n, uint8 verdictSeed, uint8 m) internal {
        uint256 due = _c(n).judgeDue;
        _rollTo(m == 0 ? 0 : m == 1 ? due : due + 1);
        uint8[5] memory table = [V_PASS, V_FAIL, V_FAIL, V_PASS, V_INCONCLUSIVE];
        (FairBindCore.SignedVerdict memory v, bytes memory vs) = book.signedVerdict(n, table[verdictSeed % 5]);
        (FairBindCore.FairBindReceipt memory r, bytes memory rs) = book.signedReceipt(n);
        FairBindCore.ReceiptProof memory proof = book.proof(n);
        bool inWindow = block.number <= due;
        try fb.judge(v, vs, r, rs, proof) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "judge", n, "");
            obs.hit(H_JUDGE);
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "judge", n, err);
            if (!inWindow) obs.hit(H_JUDGE_LATE);
        }
    }

    function timeoutJudge(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _judgmentActive);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _timeoutJudge(n, mode % 2);
        _end();
    }

    /// Mode 0 one block after judgeDue, 1 at judgeDue (too early).
    function _timeoutJudge(bytes32 n, uint8 m) internal {
        uint256 due = _c(n).judgeDue;
        _rollTo(m == 0 ? due + 1 : due);
        bool late = block.number > due;
        try fb.timeoutJudge(n) {
            _timed(true, late, true, Inv.C_DEADLINE, "timeoutJudge", n, "");
            obs.hit(H_TIMEOUT_JUDGE);
            if (_c(n).requesterRole == 3 && _c(n).state == CS_PUBLISHING) obs.hit(H_KEEPER_SERVE);
            _noteWait(n);
        } catch (bytes memory err) {
            _timed(false, late, true, Inv.C_DEADLINE, "timeoutJudge", n, err);
            if (!late) obs.hit(H_TIMEOUT_JUDGE_EARLY);
        }
    }

    function _appealable(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        return c.state == CS_INITIAL && c.reviewPath == 0 && !_evidencePending(n);
    }

    function appeal(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _appealable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _appeal(n, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at appealUntil, 2 one block after it.
    function _appeal(bytes32 n, uint8 m) internal {
        uint256 until = fb.getReview(n).appealUntil;
        _rollTo(m == 0 ? 0 : m == 1 ? until : until + 1);
        uint8 iv = _c(n).initialVerdict;
        address appellant = iv == V_FAIL ? _owner(n) : buyer;
        bool inWindow = block.number <= until;
        Inv.vm.prank(appellant);
        try fb.appeal(n) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "appeal", n, "");
            if (iv == V_INCONCLUSIVE) _flag(Inv.C_CASE, "appeal of an initial INCONCLUSIVE accepted", n, "");
            obs.hit(H_APPEAL);
        } catch (bytes memory err) {
            _timed(false, inWindow, iv != V_INCONCLUSIVE, Inv.C_DEADLINE, "appeal", n, err);
            if (!inWindow) obs.hit(H_APPEAL_LATE);
        }
    }

    function _finalizable(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        return (c.state == CS_INITIAL && !_evidencePending(n))
            || (c.assignedVerifierId == 0 && (c.state == CS_PARTY || c.state == CS_TIEBREAK));
    }

    function finalizeCase(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _finalizable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _finalize(n, mode % 3, seed);
        _end();
    }

    /// Mode 0 at the first block it is due, 1 at the last block it is not, 2
    /// later inside the review seal window.
    function _finalize(bytes32 n, uint8 m, uint256 seed) internal {
        FairBindCore.CaseView memory c = _c(n);
        uint256 rb = c.randomBlock;
        bool ready;
        if (c.state == CS_INITIAL) {
            uint256 until = fb.getReview(n).appealUntil;
            // A PASS or INCONCLUSIVE passes the recheck gate one block after its candidate block.
            uint256 first = c.initialVerdict != V_FAIL ? rb + 1 : until + 1;
            _rollTo(m == 0 ? first : m == 1 ? first - 1 : rb + 1 + (seed >> 64) % Inv.SEAL_BLOCKS);
            _hash(rb, seed);
            ready = block.number >= first;
        } else {
            // A reopened seal keeps randomBlock and ends one block plus the
            // window after the reopening (ADR 0025).
            uint256 due = _sealDue(n);
            _rollTo(m == 1 ? due : due + 1);
            ready = block.number > due;
        }
        try fb.finalizeCase(n) {
            _timed(true, ready, true, Inv.C_DEADLINE, "finalizeCase", n, "");
            obs.hit(H_FINALIZE);
        } catch (bytes memory err) {
            _timed(false, ready, true, Inv.C_DEADLINE, "finalizeCase", n, err);
            if (!ready) obs.hit(H_FINALIZE_EARLY);
        }
    }

    function _reviewWaiting(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        return c.assignedVerifierId == 0 && (c.state == CS_PARTY || c.state == CS_TIEBREAK);
    }

    function sealReview(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _reviewWaiting);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _sealReview(n, mode % 4, seed);
        _end();
    }

    /// Last block of the current review seal window: randomBlock plus the
    /// window, or the reopened window's end once the stage was reopened.
    function _sealDue(bytes32 n) internal view returns (uint256) {
        FairBindCore.CaseView memory c = _c(n);
        if (fb.getReviewReseals(n) & (uint8(1) << c.stage) != 0) return fb.getReviewResealDue(n);
        return uint256(c.randomBlock) + Inv.SEAL_BLOCKS;
    }

    /// Mode 0 inside the window, 1 at the review block (too early), 2 after
    /// the seal window, 3 inside the window with an unavailable block hash.
    /// Past the first window the seal reopens once with the same randomBlock
    /// and the hash recorded when the chain still serves it; past the reopened
    /// window, or with the hash gone before it was recorded, the stage ends as
    /// a progress failure (ADR 0021, ADR 0025).
    function _sealReview(bytes32 n, uint8 m, uint256 seed) internal {
        FairBindCore.CaseView memory c0 = _c(n);
        uint256 rb = c0.randomBlock;
        uint8 bit = uint8(1) << c0.stage;
        uint8 before = fb.getReviewReseals(n);
        bool reopened = before & bit != 0;
        uint256 due = _sealDue(n);
        _rollTo(m == 0 || m == 3 ? (reopened ? block.number : rb + 1 + (seed >> 64) % 8) : m == 1 ? rb : due + 1);
        if (m == 3 && block.number > rb && c0.randomness == 0) Inv.vm.setBlockhash(rb, bytes32(0));
        else _hash(rb, seed);
        bool ready = block.number > rb;
        bool hashServed = c0.randomness != 0 || (block.number <= rb + 256 && blockhash(rb) != 0);
        bool sealsNow = block.number <= due && hashServed;
        try fb.sealReviewRandomness(n) {
            _timed(true, ready, true, Inv.C_DEADLINE, "sealReviewRandomness", n, "");
            FairBindCore.CaseView memory c = _c(n);
            if (fb.getReviewReseals(n) != before) {
                obs.hit(H_RESEAL);
                if (reopened || sealsNow || c.randomBlock != rb || fb.getReviewResealDue(n) != block.number + 1 + Inv.SEAL_BLOCKS) {
                    _flag(Inv.C_CASE, "review seal reopened twice, without cause, or moved its randomBlock", n, "");
                }
            } else if (c.state == CS_INCONCLUSIVE || c.state == CS_FINAL) {
                obs.hit(H_REVIEW_EXPIRED);
                if (!reopened && (c0.randomness != 0 || block.number <= rb + 256)) {
                    _flag(Inv.C_CASE, "review stage ended before reopening its seal", n, "");
                }
            } else {
                obs.hit(H_REVIEW_SEAL);
                if (!sealsNow) _flag(Inv.C_CASE, "review sealed outside its window or without its hash", n, "");
            }
        } catch (bytes memory err) {
            _timed(false, ready, true, Inv.C_DEADLINE, "sealReviewRandomness", n, err);
        }
    }

    function _recheckCandidate(bytes32 n) internal view returns (bool) {
        return _appealable(n) && _c(n).initialVerdict != V_FAIL;
    }

    function openAutoRecheck(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _recheckCandidate);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _openAutoRecheck(n, mode % 3, seed);
        _end();
    }

    /// Mode 0 inside the window, 1 at the candidate block (too early), 2 after
    /// the seal window.
    function _openAutoRecheck(bytes32 n, uint8 m, uint256 seed) internal {
        uint256 rb = _c(n).randomBlock;
        _rollTo(m == 0 ? rb + 1 + (seed >> 64) % 8 : m == 1 ? rb : rb + Inv.SEAL_BLOCKS + 1);
        _hash(rb, seed);
        bool ready = block.number > rb;
        try fb.openAutoRecheck(n) {
            _timed(true, ready, true, Inv.C_DEADLINE, "openAutoRecheck", n, "");
            if (block.number <= fb.getReview(n).appealUntil) {
                _flag(Inv.C_DEADLINE, "automatic recheck opened inside the appeal window", n, "");
            }
            obs.hit(H_AUTO_RECHECK);
        } catch (bytes memory err) {
            _timed(false, ready, true, Inv.C_DEADLINE, "openAutoRecheck", n, err);
        }
    }

    // -------------------------------------------------------------- evidence

    function _evidenceRequestable(bytes32 n) internal view returns (bool) {
        if (_c(n).state != CS_INITIAL) return false;
        FairBindCore.AssignmentData[] memory list = fb.getAssignments(n);
        return list.length != 0 && !list[list.length - 1].evidenceRequested;
    }

    function requestEvidence(uint256 seed, bool bySeller, uint8 mode) external synced {
        bytes32 n = _find(seed, _evidenceRequestable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _requestEvidence(n, bySeller, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at appealUntil, 2 one block after it.
    function _requestEvidence(bytes32 n, bool bySeller, uint8 m) internal {
        FairBindCore.CaseView memory c = _c(n);
        uint256 until = fb.getReview(n).appealUntil;
        _rollTo(m == 0 ? 0 : m == 1 ? until : until + 1);
        bool inWindow = block.number <= until;
        address requester = bySeller ? _owner(n) : buyer;
        Inv.vm.prank(requester);
        try fb.requestEvidence(n, c.stage, c.attempt) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "requestEvidence", n, "");
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "requestEvidence", n, err);
        }
    }

    function discloseEvidence(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _evidencePending);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _disclose(n, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at evidenceDue, 2 one block after it.
    function _disclose(bytes32 n, uint8 m) internal {
        FairBindCore.CaseView memory c = _c(n);
        _rollTo(m == 0 ? 0 : m == 1 ? c.evidenceDue : uint256(c.evidenceDue) + 1);
        bool inWindow = block.number <= c.evidenceDue;
        try fb.discloseEvidence(n, c.stage, c.attempt, Inv.EVIDENCE) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "discloseEvidence", n, "");
            obs.hit(H_EVIDENCE_DISCLOSED);
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "discloseEvidence", n, err);
        }
    }

    function timeoutEvidence(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _evidencePending);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _timeoutEvidence(n, mode % 2);
        _end();
    }

    /// Mode 0 one block after evidenceDue, 1 at evidenceDue (too early).
    function _timeoutEvidence(bytes32 n, uint8 m) internal {
        FairBindCore.CaseView memory c = _c(n);
        _rollTo(m == 0 ? uint256(c.evidenceDue) + 1 : c.evidenceDue);
        bool late = block.number > c.evidenceDue;
        try fb.timeoutEvidence(n, c.stage, c.attempt) {
            _timed(true, late, true, Inv.C_DEADLINE, "timeoutEvidence", n, "");
            obs.hit(H_EVIDENCE_TIMEOUT);
            _noteWait(n);
        } catch (bytes memory err) {
            _timed(false, late, true, Inv.C_DEADLINE, "timeoutEvidence", n, err);
        }
    }

    // ------------------------------------------------------ serve, publication

    function _serveRequestable(bytes32 n) internal view returns (bool) {
        if (!_judgmentActive(n) || block.number > _c(n).judgeDue) return false;
        FairBindCore.AssignmentData[] memory list = fb.getAssignments(n);
        return !list[list.length - 1].serveUsed;
    }

    function requestServe(uint256 seed) external synced {
        bytes32 n = _find(seed, _serveRequestable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _requestServe(n);
        _end();
    }

    function _requestServe(bytes32 n) internal {
        bool expected = _serveRequestable(n);
        Inv.vm.prank(verifierOwner);
        try fb.requestServe(n) {
            if (!expected) _flag(Inv.C_DEADLINE, "requestServe accepted after judgeDue or twice", n, "");
            obs.hit(H_REQUEST_SERVE);
        } catch (bytes memory err) {
            if (expected) _flag(Inv.C_LIVENESS, "requestServe by the assigned verifier reverted", n, err);
        }
    }

    function _serveWait(bytes32 n) internal view returns (bool) {
        return _c(n).state == CS_SERVE_WAIT;
    }

    function served(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _serveWait);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _served(n, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at serveDue, 2 one block after it.
    function _served(bytes32 n, uint8 m) internal {
        uint256 due = _c(n).serveDue;
        _rollTo(m == 0 ? 0 : m == 1 ? due : due + 1);
        bool inWindow = block.number <= due;
        address owner = _owner(n);
        Inv.vm.prank(owner);
        try fb.served(n, keccak256(abi.encode("bundle", n))) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "served", n, "");
            obs.hit(H_SERVED);
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "served", n, err);
            if (!inWindow) obs.hit(H_SERVED_LATE);
        }
    }

    function _serveConfirm(bytes32 n) internal view returns (bool) {
        return _c(n).state == CS_SERVE_CONFIRM;
    }

    function confirmServe(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _serveConfirm);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _confirmServe(n, mode % 4);
        _end();
    }

    /// Mode 0 the requester accepts, 1 escalates, 2 finalizeServed at the end
    /// of the challenge window (too early), 3 one block after it.
    function _confirmServe(bytes32 n, uint8 m) internal {
        FairBindCore.CaseView memory c = _c(n);
        if (m < 2) {
            bool inWindow = block.number <= c.challengeUntil;
            Inv.vm.prank(c.requester);
            if (m == 0) {
                try fb.acceptServe(n) {
                    _timed(true, inWindow, true, Inv.C_DEADLINE, "acceptServe", n, "");
                } catch (bytes memory err) {
                    _timed(false, inWindow, true, Inv.C_DEADLINE, "acceptServe", n, err);
                }
            } else {
                try fb.escalate(n) {
                    _timed(true, inWindow, true, Inv.C_DEADLINE, "escalate", n, "");
                    obs.hit(H_ESCALATE);
                } catch (bytes memory err) {
                    _timed(false, inWindow, true, Inv.C_DEADLINE, "escalate", n, err);
                }
            }
            return;
        }
        _rollTo(m == 2 ? c.challengeUntil : uint256(c.challengeUntil) + 1);
        bool late = block.number > c.challengeUntil;
        try fb.finalizeServed(n) {
            _timed(true, late, true, Inv.C_DEADLINE, "finalizeServed", n, "");
        } catch (bytes memory err) {
            _timed(false, late, true, Inv.C_DEADLINE, "finalizeServed", n, err);
        }
    }

    function _publishing(bytes32 n) internal view returns (bool) {
        return _c(n).state == CS_PUBLISHING;
    }

    function publish(uint256 seed) external synced {
        bytes32 n = _find(seed, _publishing);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _publish(n);
        _end();
    }

    function _publish(bytes32 n) internal {
        bytes16 key = book.keyOf(n);
        FairBindCore.CanonicalRequest memory req = book.request(key);
        (FairBindCore.FairBindReceipt memory r, bytes memory sig) = book.signedReceipt(n);
        bool inWindow = block.number <= _c(n).publishDue;
        address owner = _owner(n);
        Inv.vm.prank(owner);
        try fb.publish(n, key, req, Inv.RESPONSE_BODY, r, sig) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "publish", n, "");
            obs.hit(H_PUBLISH);
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "publish", n, err);
        }
    }

    function _serveTimeoutCandidate(bytes32 n) internal view returns (bool) {
        uint8 s = _c(n).state;
        return s == CS_SERVE_WAIT || s == CS_PUBLISHING;
    }

    function timeoutServe(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _serveTimeoutCandidate);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _timeoutServe(n, mode % 2);
        _end();
    }

    /// Mode 0 one block after the serve or publication deadline, 1 at it.
    function _timeoutServe(bytes32 n, uint8 m) internal {
        FairBindCore.CaseView memory c = _c(n);
        uint256 due = c.state == CS_SERVE_WAIT ? c.serveDue : c.publishDue;
        _rollTo(m == 0 ? due + 1 : due);
        bool late = block.number > due;
        try fb.timeoutServe(n) {
            _timed(true, late, true, Inv.C_DEADLINE, "timeoutServe", n, "");
            obs.hit(H_TIMEOUT_SERVE);
        } catch (bytes memory err) {
            _timed(false, late, true, Inv.C_DEADLINE, "timeoutServe", n, err);
            if (!late) obs.hit(H_TIMEOUT_SERVE_EARLY);
        }
    }

    // ------------------------------------------------------ sample receipts

    function _receiptTimeoutCandidate(bytes32 n) internal view returns (bool) {
        uint8 s = _c(n).state;
        return fb.getSampleReceiptDue(n) != 0 && s != CS_FINAL && s != CS_INCONCLUSIVE && s != CS_UNSERVED;
    }

    function timeoutSampleReceipt(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _receiptTimeoutCandidate);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _timeoutReceipt(n, mode % 2);
        _end();
    }

    /// Mode 0 one block after the receipt deadline, 1 at it (ADR 0024).
    function _timeoutReceipt(bytes32 n, uint8 m) internal {
        uint256 due = fb.getSampleReceiptDue(n);
        _rollTo(m == 0 ? due + 1 : due);
        bool late = block.number > due;
        bool live = _receiptTimeoutCandidate(n);
        try fb.timeoutSampleReceipt(n) {
            _timed(true, late, live, Inv.C_DEADLINE, "timeoutSampleReceipt", n, "");
            obs.hit(H_RECEIPT_TIMEOUT);
            if (_c(n).state != CS_UNSERVED) _flag(Inv.C_CASE, "timeoutSampleReceipt did not end the case UNSERVED", n, "");
        } catch (bytes memory err) {
            _timed(false, late, live, Inv.C_DEADLINE, "timeoutSampleReceipt", n, err);
        }
    }

    function _recoveryActive(bytes32 n) internal view returns (bool) {
        uint8 s = fb.getBuyerRecovery(n).state;
        return s == CS_SERVE_WAIT || s == CS_SERVE_CONFIRM;
    }

    function buyerRecovery(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _recoveryActive);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _buyerRecovery(n, mode % 3);
        _end();
    }

    /// Steps an independent buyer recovery. Mode 0 serves or accepts in time,
    /// 1 times out or finalizes at the deadline (too early), 2 one block after.
    function _buyerRecovery(bytes32 n, uint8 m) internal {
        FairBindCore.CaseView memory r = fb.getBuyerRecovery(n);
        if (r.state == CS_SERVE_WAIT) {
            if (m == 0) {
                bool inWindow = block.number <= r.serveDue;
                address owner = _owner(n);
                Inv.vm.prank(owner);
                try fb.buyerServed(n, keccak256(abi.encode("recovery", n))) {
                    _timed(true, inWindow, true, Inv.C_DEADLINE, "buyerServed", n, "");
                } catch (bytes memory err) {
                    _timed(false, inWindow, true, Inv.C_DEADLINE, "buyerServed", n, err);
                }
                return;
            }
            _rollTo(m == 1 ? r.serveDue : uint256(r.serveDue) + 1);
            bool late = block.number > r.serveDue;
            try fb.timeoutBuyerServe(n) {
                _timed(true, late, true, Inv.C_DEADLINE, "timeoutBuyerServe", n, "");
                obs.hit(H_RECOVERY_TIMEOUT);
            } catch (bytes memory err) {
                _timed(false, late, true, Inv.C_DEADLINE, "timeoutBuyerServe", n, err);
            }
            return;
        }
        if (m == 0) {
            bool inWindow = block.number <= r.challengeUntil;
            Inv.vm.prank(buyer);
            try fb.acceptBuyerServe(n) {
                _timed(true, inWindow, true, Inv.C_DEADLINE, "acceptBuyerServe", n, "");
            } catch (bytes memory err) {
                _timed(false, inWindow, true, Inv.C_DEADLINE, "acceptBuyerServe", n, err);
            }
            return;
        }
        _rollTo(m == 1 ? r.challengeUntil : uint256(r.challengeUntil) + 1);
        bool due = block.number > r.challengeUntil;
        try fb.finalizeBuyerServed(n) {
            _timed(true, due, true, Inv.C_DEADLINE, "finalizeBuyerServed", n, "");
        } catch (bytes memory err) {
            _timed(false, due, true, Inv.C_DEADLINE, "finalizeBuyerServed", n, err);
        }
    }

    // ---------------------------------------------------------------- refunds

    function _epochClaimable(bytes32 n) internal view returns (bool) {
        FairBindCore.PurchaseView memory p = _p(n);
        return fb.getAnchor(p.sellerId, p.epoch).state == E_FAILED && !_finalized(n);
    }

    function claimEpochFailure(uint256 seed) external synced {
        bytes32 n = _find(seed, _epochClaimable);
        _begin(Inv.K_CLAIM_EPOCH, n);
        if (n != 0) _claimEpochFailure(n);
        _end();
    }

    function _claimEpochFailure(bytes32 n) internal {
        kind = Inv.K_CLAIM_EPOCH;
        subject = n;
        try fb.claimEpochFailure(n) {
            obs.hit(H_EPOCH_CLAIM);
        } catch (bytes memory err) {
            _flag(Inv.C_LIVENESS, "claimEpochFailure reverted", n, err);
        }
    }

    function _refundable(bytes32 n) internal view returns (bool) {
        return _p(n).financialState == F_REFUNDABLE;
    }

    function claimRefund(uint256 seed) external synced {
        bytes32 n = _find(seed, _refundable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _claimRefund(n);
        _end();
    }

    function _claimRefund(bytes32 n) internal {
        uint256 before = token.balanceOf(buyer);
        try fb.claimRefund(n) {
            obs.hit(H_REFUND);
            if (token.balanceOf(buyer) < before + _p(n).value) {
                _flag(Inv.C_CLAIM, "refund paid less than the purchase amount", n, "");
            }
        } catch (bytes memory err) {
            _flag(Inv.C_LIVENESS, "claimRefund of a refundable purchase reverted", n, err);
        }
    }

    function _frozenClaimable(bytes32 n) internal view returns (bool) {
        FairBindCore.BondView memory b = _bondOf(n);
        uint8 st = _p(n).financialState;
        return b.freezeState == Z_OPEN && obs.heldByModel(b.bondId, _p(n).settledBlock)
            && (st == F_DEFERRED || st == F_RELEASABLE) && fb.purchaseState(n) != F_FORFEITED;
    }

    function _any(bytes32) internal pure returns (bool) {
        return true;
    }

    /// Frozen-pool claim with a receipt: now (mode 0), at the last block of
    /// the window (1), one block after it (2), or signed with a key that is
    /// not the purchase seller's (3). Falls back to an arbitrary purchase to
    /// exercise the rejection of entries outside any open window.
    function claimFrozen(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _frozenClaimable);
        if (n == 0) n = _find(seed, _any);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _claimFrozen(n, mode % 4);
        _end();
    }

    function _claimFrozen(bytes32 n, uint8 m) internal {
        FairBindCore.PurchaseView memory p = _p(n);
        FairBindCore.BondView memory b = _bondOf(n);
        if (b.freezeState == Z_OPEN && (m == 1 || m == 2)) {
            _rollTo(m == 1 ? b.claimUntilBlock : uint256(b.claimUntilBlock) + 1);
        }
        (FairBindCore.FairBindReceipt memory r, bytes memory sig) = m == 3
            ? book.foreignReceipt(n, SELLER_KEY_BASE + 99)
            : book.signedReceipt(n);
        FairBindCore.ReceiptProof memory proof = book.proof(n);
        bool inWindow = b.freezeState == Z_OPEN && block.number <= b.claimUntilBlock;
        bool eligible = _frozenClaimable(n) && fb.getFrozenPool(b.bondId).poolBalance >= p.value;
        uint256 before = token.balanceOf(buyer);
        try fb.claimRefund(n, r, sig, proof) {
            FairBindCore.BondView memory a = _bondOf(n);
            if (!inWindow) _flag(Inv.C_DEADLINE, "frozen claim succeeded outside the claim window", n, "");
            else if (!eligible) _flag(Inv.C_CLAIM, "frozen claim accepted for an ineligible entry", n, "");
            if (m == 3) _flag(Inv.C_CLAIM, "frozen claim accepted with a foreign receipt signature", n, "");
            if (a.claimedTotal != b.claimedTotal + p.value || token.balanceOf(buyer) < before + p.value) {
                _flag(Inv.C_CLAIM, "frozen claim paid a wrong amount", n, "");
            }
            obs.hit(H_CLAIM);
        } catch (bytes memory err) {
            if (m == 3) obs.hit(H_CLAIM_FOREIGN);
            else if (eligible && !inWindow) obs.hit(H_CLAIM_LATE);
            else if (!eligible) obs.hit(H_CLAIM_EARLY_WINDOW);
            if (eligible && inWindow && m != 3) {
                _flag(Inv.C_LIVENESS, "frozen claim with a valid receipt reverted", n, err);
            }
        }
    }

    function forfeitUnclaimed(uint256 seed, uint8 mode) external synced {
        uint32 bondId = obs.bondIds(seed % obs.bondCount());
        _begin(Inv.K_OTHER, bytes32(uint256(bondId)));
        _forfeit(bondId, mode % 2);
        _end();
    }

    /// Mode 0 one block after the claim window, 1 at its last block.
    function _forfeit(uint32 bondId, uint8 m) internal {
        FairBindCore.BondView memory b = fb.getBond(bondId);
        if (b.freezeState == Z_OPEN) _rollTo(m == 0 ? uint256(b.claimUntilBlock) + 1 : b.claimUntilBlock);
        bool ready = b.freezeState == Z_OPEN && block.number > b.claimUntilBlock;
        bytes32 tag = bytes32(uint256(bondId));
        // The unclaimed pool is the frozen window: entries settled after a
        // reinstatement are not forfeited (ADR 0021). It is an upper bound of
        // the window when the account holds unreleased entries settled before
        // the window's start (ADR 0030).
        uint256 pool = fb.getFrozenPool(bondId).poolBalance;
        // A window with an unencumbered entry outside the model window (before
        // its start or between its spans) that a single sum would take must
        // close itemized.
        bool mustItemize = b.freezeState == Z_OPEN && obs.unheldThrough(bondId, obs.lastConfirm(bondId));
        try fb.forfeitUnclaimed(bondId) {
            FairBindCore.BondView memory a = fb.getBond(bondId);
            _timed(true, ready, true, Inv.C_DEADLINE, "forfeitUnclaimed", tag, "");
            uint256 taken = a.forfeitedTotal - b.forfeitedTotal;
            FairBindCore.ForfeitWindow[] memory w = fb.getForfeitWindows(bondId);
            bool itemized = w.length != 0 && w[w.length - 1].itemized;
            // One sum takes exactly the unclaimed pool; an itemized close takes
            // nothing at once and forfeits each entry when it is swept.
            if (itemized ? taken != 0 : taken != pool) {
                _flag(Inv.C_FORFEIT, "forfeiture differs from the unclaimed pool", tag, "");
            }
            if (mustItemize && !itemized) {
                _flag(Inv.C_FORFEIT, "forfeiture of one sum with an entry outside the frozen window", tag, "");
            }
            obs.hit(H_FORFEIT);
        } catch (bytes memory err) {
            _timed(false, ready, true, Inv.C_DEADLINE, "forfeitUnclaimed", tag, err);
            if (b.freezeState == Z_OPEN && !ready) obs.hit(H_FORFEIT_EARLY);
        }
    }

    // ---------------------------------------------------------------- release

    function _releaseCandidate(bytes32 n) internal view returns (bool) {
        uint8 st = _p(n).financialState;
        return st == F_DEFERRED || st == F_RELEASABLE;
    }

    struct ReleasePre {
        bool deliveredSampled;
        bool frozen;
        bool forfeited;
        bool sampled;
        bool recovery;
        bool timely;
        bool wallTimely;
        uint256 paused;
        uint8 epochState;
        uint8 caseState;
        uint8 finalVerdict;
        uint64 confirm;
        uint256 ownerBalance;
    }

    function releasePurchase(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _releaseCandidate);
        _begin(Inv.K_RELEASE, n);
        if (n != 0) _release(n, mode % 2);
        _end();
    }

    /// Mode 0 now, 1 at the first block every release condition holds.
    function _release(bytes32 n, uint8 m) internal {
        kind = Inv.K_RELEASE;
        subject = n;
        FairBindCore.PurchaseView memory p = _p(n);
        FairBindCore.AnchorView memory a = fb.getAnchor(p.sellerId, p.epoch);
        uint32 bondId = fb.getSeller(p.sellerId).bondId;
        obs.syncWaits();
        if (m == 1) {
            uint256 target = uint256(p.claimUntil) + 1;
            // deferBlocks of unpaused blocks: the paused blocks so far push the
            // release block back (ADR 0029).
            uint256 releaseAt = uint256(p.releaseBlock) + obs.pausedSince(bondId, p.settledBlock);
            if (releaseAt > target) target = releaseAt;
            if (p.retainUntil > target) target = p.retainUntil;
            if (a.state == E_SEALED && uint256(a.sealDeadline) + Inv.OPEN_BLOCKS + 1 > target) {
                target = uint256(a.sealDeadline) + Inv.OPEN_BLOCKS + 1;
            }
            _rollTo(target);
            // The move may have anchored or sealed the epoch.
            a = fb.getAnchor(p.sellerId, p.epoch);
        }
        ReleasePre memory r;
        r.frozen = _frozen(n);
        r.forfeited = fb.purchaseState(n) == F_FORFEITED;
        (r.sampled,) = fb.isSampled(n);
        r.deliveredSampled = r.sampled && _c(n).state == CS_DELIVERED && _c(n).trigger == T_NON_DELIVERY;
        r.recovery = _recoveryOpen(n);
        r.epochState = a.state;
        r.caseState = _c(n).state;
        r.finalVerdict = _c(n).finalVerdict;
        obs.syncWaits();
        r.paused = obs.pausedSince(bondId, p.settledBlock);
        // wallTimely: every release condition counted in wall blocks, as
        // before ADR 0029; timely adds deferBlocks of unpaused blocks.
        r.wallTimely = block.number > p.claimUntil && block.number > uint256(a.sealDeadline) + Inv.OPEN_BLOCKS
            && block.number >= p.releaseBlock && block.number >= p.retainUntil;
        r.timely = r.wallTimely && block.number - r.paused >= p.releaseBlock;
        // The confirmed failure whose window [c, t] holds the entry (ADR 0030).
        r.confirm = obs.confirmedWindowOf(fb.getSeller(p.sellerId).bondId, p.settledBlock);
        address owner = _owner(n);
        r.ownerBalance = token.balanceOf(owner);
        try fb.releasePurchase(n) {
            _released(n, p, r, owner);
        } catch (bytes memory err) {
            if (r.frozen) obs.hit(H_RELEASE_FROZEN);
            if (r.caseState == CS_WAITING) obs.hit(H_RELEASE_WAITING);
            if (r.paused != 0 && block.number >= p.releaseBlock && block.number - r.paused < p.releaseBlock) {
                obs.hit(H_RELEASE_PAUSED);
            }
            bool live = !r.frozen && !r.forfeited && !r.recovery && r.epochState == E_SEALED && r.timely
                && ((r.caseState == 0 && !r.sampled) || (_done(r.caseState) && !r.deliveredSampled));
            if (live) _flag(Inv.C_LIVENESS, "release of a releasable purchase reverted", n, err);
        }
    }

    function _released(bytes32 n, FairBindCore.PurchaseView memory p, ReleasePre memory r, address owner) internal {
        uint8 post = _p(n).financialState;
        if (post == F_FORFEITED) {
            if (!r.forfeited) _flag(Inv.C_FORFEIT, "release forfeited an entry outside a closed window", n, "");
            return;
        }
        if (post != F_RELEASED) {
            _flag(Inv.C_RELEASE, "releasePurchase succeeded without releasing", n, "");
            return;
        }
        obs.hit(H_RELEASE);
        if (r.frozen) _flag(Inv.C_RELEASE, "frozen entry released", n, "");
        if (r.forfeited) _flag(Inv.C_RELEASE, "forfeited entry released", n, "");
        if (r.recovery) _flag(Inv.C_RELEASE, "entry released during an open buyer recovery", n, "");
        if (r.epochState != E_SEALED || !r.wallTimely) {
            _flag(Inv.C_RELEASE, "entry released before its release conditions", n, "");
        }
        if (block.number - r.paused < p.releaseBlock) {
            _flag(Inv.C_RELEASE, string.concat("entry released before deferBlocks unpaused blocks, paused ",
                Inv.toString(r.paused)), n, "");
        }
        if (r.caseState == 0 && r.sampled) _flag(Inv.C_RELEASE, "sampled entry released without an opened case", n, "");
        if (r.deliveredSampled) {
            _flag(Inv.C_RELEASE, "sampled entry released after a delivered dispute without its sample case", n, "");
        }
        if (r.caseState == CS_WAITING) _flag(Inv.C_RELEASE, "entry released while its case waits for an assignment", n, "");
        if (r.caseState != 0 && !_done(r.caseState)) _flag(Inv.C_RELEASE, "entry released before its case ended", n, "");
        if (r.caseState == CS_FINAL && r.finalVerdict == V_FAIL) _flag(Inv.C_RELEASE, "failed entry released", n, "");
        if (r.confirm != 0) {
            _flag(Inv.C_LEAK, string.concat("principal settled at block ", Inv.toString(p.settledBlock),
                " released to the seller after a final failure of its bond at block ", Inv.toString(r.confirm)), n, "");
        }
        if (token.balanceOf(owner) < r.ownerBalance + p.value) {
            _flag(Inv.C_RELEASE, "release paid less than the principal", n, "");
        }
    }

    // ------------------------------------------------- freeze and seller status

    function _pendingInitialFail(bytes32 n) internal view returns (bool) {
        FairBindCore.CaseView memory c = _c(n);
        return c.initialVerdict == V_FAIL && _open(c.state);
    }

    function freezeSellerDeferred(uint256 seed) external synced {
        bytes32 n = _find(seed, _pendingInitialFail);
        if (n == 0) n = _find(seed, _any);
        _begin(Inv.K_FREEZE, n);
        if (n != 0) _freezeDeferred(n);
        _end();
    }

    function _freezeDeferred(bytes32 n) internal {
        kind = Inv.K_FREEZE;
        subject = n;
        FairBindCore.BondView memory b = _bondOf(n);
        bool expected = _pendingInitialFail(n) && obs.freezeOnInitialFail() && b.freezeState != Z_FROZEN
            && b.freezeState != Z_OPEN;
        try fb.freezeSellerDeferred(n) {
            if (!expected) _flag(Inv.C_STATUS, "freezeSellerDeferred accepted without a pending initial FAIL", n, "");
            obs.hit(H_FREEZE_DEFERRED);
        } catch (bytes memory err) {
            if (expected) _flag(Inv.C_LIVENESS, "freezeSellerDeferred reverted", n, err);
        }
    }

    function releaseFrozen(uint256 seed) external synced {
        uint32 bondId = obs.bondIds(seed % obs.bondCount());
        _begin(Inv.K_OTHER, bytes32(uint256(bondId)));
        _releaseFrozen(bondId);
        _end();
    }

    function _releaseFrozen(uint32 bondId) internal {
        FairBindCore.BondView memory b = fb.getBond(bondId);
        FairBindCore.CaseView memory c = _c(b.freezeNonce);
        bool expected = b.freezeState == Z_FROZEN && (c.state == CS_DELIVERED || c.state == CS_INCONCLUSIVE
            || (c.state == CS_FINAL && c.finalVerdict != V_FAIL));
        try fb.releaseFrozen(bondId) {
            if (!expected) {
                _flag(Inv.C_STATUS, "releaseFrozen cleared a freeze whose trigger did not end cleanly", b.freezeNonce, "");
            }
            obs.hit(H_RELEASE_FROZEN_BOND);
        } catch (bytes memory err) {
            if (expected) _flag(Inv.C_LIVENESS, "releaseFrozen reverted", b.freezeNonce, err);
        }
    }

    function reinstateSeller(uint256 seed) external synced {
        uint32 sid = obs.sellerIds(seed % obs.sellerCount());
        _begin(Inv.K_REINSTATE, bytes32(uint256(sid)));
        _reinstate(sid);
        _end();
    }

    /// Reinstatement is admitted while the claim window is open (ADR 0021),
    /// never while FROZEN, pending, sanctioned or below one penalty.
    function _reinstate(uint32 sid) internal {
        FairBindCore.SellerView memory s = fb.getSeller(sid);
        FairBindCore.BondView memory b = fb.getBond(s.bondId);
        bool expected = s.status == uint8(FairBindCore.SellerStatus.SUSPENDED) && !b.sanctioned
            && b.freezeState != Z_FROZEN && b.balance >= _unit(s.bondId) && obs.pendingTriggers(s.bondId) == 0;
        Inv.vm.prank(s.owner);
        try fb.reinstateSeller(sid) {
            if (!expected) {
                _flag(Inv.C_STATUS, "reinstatement accepted while frozen, pending, sanctioned or underfunded",
                    bytes32(uint256(sid)), "");
            }
            if (b.freezeState == Z_OPEN && !fb.getClaimReentry(s.bondId).reopened) {
                _flag(Inv.C_STATUS, "reinstatement during the claim window did not reopen the account",
                    bytes32(uint256(sid)), "");
            }
            obs.hit(H_REINSTATE);
        } catch (bytes memory err) {
            if (expected) _flag(Inv.C_LIVENESS, "reinstatement refused", bytes32(uint256(sid)), err);
        }
    }

    function topUpBond(uint256 seed, uint256 amountSeed) external synced {
        uint32 bondId = obs.bondIds(seed % obs.bondCount());
        _begin(Inv.K_TOPUP, bytes32(uint256(bondId)));
        _topUp(bondId, 1 + amountSeed % (2 * penalty));
        _end();
    }

    function _topUp(uint32 bondId, uint256 amount) internal {
        FairBindCore.BondView memory b = fb.getBond(bondId);
        Inv.vm.prank(b.owner);
        try fb.topUpBond(bondId, uint128(amount)) {
            obs.noteTopUp(bondId, amount);
            obs.hit(H_TOPUP);
        } catch (bytes memory err) {
            if (b.status == uint8(FairBindCore.BondStatus.ACTIVE)) _flag(Inv.C_LIVENESS, "top-up refused", 0, err);
        }
    }

    /// Adds a registration to a bond account; the shared bucket must not change.
    function registerSeller(uint256 seed) external synced {
        uint32 bondId = obs.bondIds(seed % obs.bondCount());
        _begin(Inv.K_OTHER, bytes32(uint256(bondId)));
        if (extraSellers < 2) {
            FairBindCore.BondView memory b = fb.getBond(bondId);
            bool expected = b.status == uint8(FairBindCore.BondStatus.ACTIVE) && !b.sanctioned && b.balance >= _unit(bondId)
                && b.freezeState != Z_FROZEN && b.freezeState != Z_OPEN;
            uint256 level = obs.modelLevel(bondId);
            bool ok = _register(bondId, b.owner);
            if (ok) {
                extraSellers++;
                obs.hit(H_REGISTER);
                if (!expected) _flag(Inv.C_STATUS, "registration accepted on a frozen or sanctioned bond", 0, "");
                if (fb.quoteSeller(obs.sellerIds(obs.sellerCount() - 1)).bucketBalancePpm != level) {
                    _flag(Inv.C_BUCKET, "a new registration changed the bond bucket", 0, "");
                }
            } else if (expected) {
                _flag(Inv.C_LIVENESS, "registration refused", 0, "");
            }
        }
        _end();
    }

    // ----------------------------------------------------- design 2 actions

    /// Changes the value cap of a bond account between CAP_LOW and CAP_HIGH in
    /// the base tier (rule D2-14). The balance must cover k * b(V*') at the new
    /// terms; a lowered cap keeps the old one as V* for retentionBlocks. Only
    /// under design 2 terms; otherwise it must revert.
    function setBondTerms(uint256 seed, uint8 mode) external synced {
        uint32 bondId = obs.bondIds(seed % obs.bondCount());
        _begin(Inv.K_TERMS, bytes32(uint256(bondId)));
        FairBindCore.BondView memory b = fb.getBond(bondId);
        uint96 cap = mode % 2 == 0 ? Inv.CAP_LOW : Inv.CAP_HIGH;
        Inv.vm.prank(b.owner);
        try fb.setBondTerms(bondId, cap, Inv.BASE_TIER) {
            obs.hit(H_TERMS);
            if (!Inv.tiered()) _flag(Inv.C_STATUS, "setBondTerms accepted without profile terms", 0, "");
            if (b.status != uint8(FairBindCore.BondStatus.ACTIVE) || b.sanctioned) {
                _flag(Inv.C_STATUS, "setBondTerms accepted on an inactive or sanctioned bond", 0, "");
            }
            FairBindCore.BondTerms memory t = fb.getBondTerms(bondId);
            if (t.sampleScaleValue != cap || fb.getBond(bondId).balance < _unit(bondId)) {
                _flag(Inv.C_COUNTERS, "terms not applied or balance below the new unit bond", 0, "");
            }
        } catch (bytes memory err) {
            bool expected = Inv.tiered() && b.status == uint8(FairBindCore.BondStatus.ACTIVE) && !b.sanctioned
                && Inv.selector(err) != FairBindCore.InsufficientSellerBond.selector;
            if (expected) _flag(Inv.C_LIVENESS, "setBondTerms refused", 0, err);
            // A reverted call changed no terms: the observer must not apply
            // them to its model of the window scale.
            kind = Inv.K_OTHER;
        }
        _end();
    }

    function _receiptPending(bytes32 n) internal view returns (bool) {
        return fb.getSampleReceiptDue(n) != 0;
    }

    function submitSampleReceipt(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _receiptPending);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _submitReceipt(n, mode % 3);
        _end();
    }

    /// Mode 0 now, 1 at the receipt deadline, 2 one block after it (rule
    /// D2-17): anyone may put the seller-signed receipt and its inclusion
    /// proof on chain until the deadline, never after.
    function _submitReceipt(bytes32 n, uint8 m) internal {
        uint256 due = fb.getSampleReceiptDue(n);
        _rollTo(m == 0 ? 0 : m == 1 ? due : due + 1);
        (FairBindCore.FairBindReceipt memory r, bytes memory rs) = book.signedReceipt(n);
        FairBindCore.ReceiptProof memory proof = book.proof(n);
        bool inWindow = block.number <= due;
        Inv.vm.prank(buyer);
        try fb.submitSampleReceipt(n, r, rs, proof) {
            _timed(true, inWindow, true, Inv.C_DEADLINE, "submitSampleReceipt", n, "");
            obs.hit(H_RECEIPT_SUBMIT);
            if (fb.getSampleReceiptDue(n) != 0) _flag(Inv.C_CASE, "receipt on chain left its deadline set", n, "");
        } catch (bytes memory err) {
            _timed(false, inWindow, true, Inv.C_DEADLINE, "submitSampleReceipt", n, err);
        }
    }

    function _sellerAppealable(bytes32 n) internal view returns (bool) {
        return _appealable(n) && _c(n).initialVerdict == V_FAIL && block.number <= fb.getReview(n).appealUntil;
    }

    /// A seller appeal against an initial FAIL whose review cannot progress
    /// (rule D2-15): the seller appeals, then in mode 0 both review seal
    /// windows lapse, in mode 1 the review is sealed and every assignment of
    /// the stage times out. Each step is observed on its own; the stage must
    /// end FINAL(FAIL), never INCONCLUSIVE (invariant_stalledSellerAppealUpholdsTheFail).
    function stalledSellerAppeal(uint256 seed, uint8 mode) external synced {
        bytes32 n = _find(seed, _sellerAppealable);
        _begin(Inv.K_OTHER, n);
        if (n != 0) _appeal(n, 0);
        _end();
        if (n == 0 || _c(n).reviewPath != 1) return;
        if (mode % 2 == 0) {
            for (uint256 k; k < 2 && _reviewWaiting(n); k++) {
                _begin(Inv.K_OTHER, n);
                _finalize(n, 2, seed);
                _end();
            }
            return;
        }
        if (!_reviewWaiting(n)) return;
        _begin(Inv.K_OTHER, n);
        _sealReview(n, 0, seed);
        _end();
        for (uint256 k; k < 3 && _judgmentActive(n); k++) {
            _begin(Inv.K_OTHER, n);
            _timeoutJudge(n, 0);
            _end();
        }
    }
}
