// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
// Imported so that the mutation artifacts are compiled with this file.
import { WholeFreezeDelivery } from "./NarrowFreezeMutants.sol";
import { WholeFreezeSettlement } from "./NarrowFreezeRegressionMutants.sol";

/// Regression tests of the narrow freeze, written from the rule text
/// (sec_rule.tex, Narrow Freeze and Confirmed Failures) and ADR 0030: a
/// confirmed failure fixes the settlement block s_f of the sale it is tied to
/// and freezes every unreleased item settled at or after s_f, including items
/// whose cases still wait; items settled before s_f keep their release
/// schedule; each frozen item opens a claim period.
///
/// Each scenario is an external function that reverts with a fixed message at
/// its first check of the narrow window. The production build must pass it;
/// a mutation build whose freeze starts at block zero (the whole freeze of ADR
/// 0012) must revert with exactly that message, so the mutation is caught by
/// the behavior under test and not by an unrelated failure.
contract NarrowFreezeRegressionTest is ModuleSwapBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant H = 7_000;
    uint256 internal constant LIABILITY = G + 1_000_000;
    uint8 internal constant DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);
    uint8 internal constant HELD = uint8(FairBindCore.FinancialState.HELD);
    uint8 internal constant REFUNDABLE = uint8(FairBindCore.FinancialState.REFUNDABLE);
    uint8 internal constant FROZEN_CLAIMABLE = uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE);
    uint8 internal constant RELEASED = uint8(FairBindCore.FinancialState.RELEASED);
    uint8 internal constant REFUNDED = uint8(FairBindCore.FinancialState.REFUNDED);
    uint8 internal constant FORFEITED = uint8(FairBindCore.FinancialState.FORFEITED);
    uint8 internal constant CLAIM_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);
    uint8 internal constant CLAIM_CLOSED = uint8(FairBindCore.FreezeState.CLAIM_CLOSED);
    uint8 internal constant WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);
    address internal constant KEEPER = address(0x4EE9E2);

    string internal constant WHOLE_DELIVERY = "NarrowFreezeMutants.sol:WholeFreezeDelivery";
    string internal constant WHOLE_SETTLEMENT = "NarrowFreezeRegressionMutants.sol:WholeFreezeSettlement";

    // ------------------------------------------------------------- helpers

    function _modules(uint256 index, string memory name) internal pure returns (string[10] memory names) {
        names = _productionModules();
        if (bytes(name).length != 0) names[index] = name;
    }

    function _list(bytes32 a, bytes32 b, bytes32 c) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](3);
        ns[0] = a;
        ns[1] = b;
        ns[2] = c;
    }

    function _list(bytes32 a, bytes32 b, bytes32 c, bytes32 d) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](4);
        ns[0] = a;
        ns[1] = b;
        ns[2] = c;
        ns[3] = d;
    }

    function _list(bytes32 a, bytes32 b, bytes32 c, bytes32 d, bytes32 e) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](5);
        ns[0] = a;
        ns[1] = b;
        ns[2] = c;
        ns[3] = d;
        ns[4] = e;
    }

    /// Calls this contract and returns whether the call reverted with `sel`.
    function _revertsWith(bytes memory data, bytes4 sel) internal returns (bool) {
        (bool ok, bytes memory err) = address(this).call(data);
        if (ok || err.length < 4) return false;
        bytes4 got;
        assembly {
            got := mload(add(err, 32))
        }
        return got == sel;
    }

    function _releaseReverts(bytes32 n, bytes4 sel) internal returns (bool) {
        return _revertsWith(abi.encodeCall(this.releaseExternal, (n)), sel);
    }

    function _claimReverts(bytes32 n, bytes4 sel) internal returns (bool) {
        return _revertsWith(abi.encodeCall(this.claimProvedExternal, (n)), sel);
    }

    /// claimRefund with the seller-signed receipt and, once the epoch is
    /// anchored, its inclusion proof from the last tree built.
    function claimProvedExternal(bytes32 n) external {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        uint8 s = fairbind.getAnchor(p.sellerId, p.epoch).state;
        bool anchored = s == uint8(FairBindCore.EpochState.ANCHORED) || s == uint8(FairBindCore.EpochState.SEALED);
        _claimWith(n, anchored ? _proof(n) : _emptyProof());
    }

    function _expectMutantMessage(bytes memory call, string memory message) internal {
        (bool ok, bytes memory err) = address(this).call(call);
        require(!ok, "mutation not caught");
        require(keccak256(err) == keccak256(abi.encodeWithSignature("Error(string)", message)), "caught for another reason");
    }

    // ----------------------------------------- 1. earlier sale keeps schedule

    /// Purchases e (block 10), e1 (block 19), d and d2 (block 20, d first), l
    /// (block 30). d ends UNSERVED, a confirmed failure with s_f = 20. Inside
    /// the claim window, e and e1 are released once their release conditions
    /// hold; d (refunded through its case), d2 (settled in s_f after d) and l
    /// are refused, and after the window the seller never receives d2 or l.
    function scenarioEarlierSaleReleased(string memory delivery) external {
        _deployModules(_modules(DELIVERY, delivery), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(19);
        bytes32 e1 = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        bytes32 d2 = _purchase(G);
        hv.roll(30);
        bytes32 l = _purchase(G);
        _unserved(d);
        uint64 failureBlock = uint64(_now());
        _anchorAndSealUnsampled(0, _list(e, e1, d, d2, l));
        FairBindCore.BondView memory b = _bond();
        require(b.freezeState == CLAIM_OPEN, "claim window open");
        require(fairbind.purchaseState(d) == REFUNDABLE, "failing sale refundable through its case");
        hv.roll(uint256(fairbind.getPurchase(e1).releaseBlock));
        require(_now() <= b.claimUntilBlock, "fixture: inside the claim window");
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        (bool okE,) = address(this).call(abi.encodeCall(this.releaseExternal, (e)));
        (bool okE1,) = address(this).call(abi.encodeCall(this.releaseExternal, (e1)));
        require(okE && okE1, "earlier sale released");
        require(fairbind.getPurchase(e).financialState == RELEASED, "e released");
        require(fairbind.getPurchase(e1).financialState == RELEASED, "e1 (s_f - 1) released");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + 2 * G, "seller paid the earlier sales");
        // The window is [s_f, failure block].
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].from == 20 && spans[0].through == failureBlock, "window [s_f, failure]");
        require(_releaseReverts(d, FairBindCore.InvalidTransition.selector), "failing sale not released");
        require(_releaseReverts(d2, FairBindCore.FrozenEntry.selector), "entry settled in s_f frozen");
        require(_releaseReverts(l, FairBindCore.FrozenEntry.selector), "later entry frozen");
        require(fairbind.purchaseState(d2) == FROZEN_CLAIMABLE, "d2 claimable");
        require(fairbind.purchaseState(l) == FROZEN_CLAIMABLE, "l claimable");
        // Still refused at the last block of the window, and never paid to the
        // seller after it.
        hv.roll(uint256(b.claimUntilBlock));
        require(_releaseReverts(l, FairBindCore.FrozenEntry.selector), "frozen to the end of the window");
        hv.roll(uint256(b.claimUntilBlock) + 1);
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        hv.prank(KEEPER);
        fairbind.releasePurchase(d2);
        hv.prank(KEEPER);
        fairbind.releasePurchase(l);
        require(fairbind.getPurchase(d2).financialState == FORFEITED, "d2 forfeited");
        require(fairbind.getPurchase(l).financialState == FORFEITED, "l forfeited");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + 2 * G, "frozen entries never paid to the seller");
    }

    function test_earlierSaleReleasedAfterLaterFailure() public {
        this.scenarioEarlierSaleReleased("");
    }

    function test_earlierSaleReleasedAfterLaterFailure_wholeFreezeMutantCaught() public {
        _expectMutantMessage(abi.encodeCall(this.scenarioEarlierSaleReleased, (WHOLE_DELIVERY)), "earlier sale released");
    }

    // ------------------------------------ 2. waiting item after s_f is frozen

    /// A profile in which every purchase is sampled and every first search of
    /// checkpoint 1 is exhausted: a verifier bond of 10 USDC leaves
    /// (10 - 1) * 0.1 = 0.9 USDC of room, below one case (1.01 USDC).
    function _waitProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.verifierExposurePpm = 100_000;
    }

    function _postReceipt(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.submitSampleReceipt(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(n));
    }

    /// Tops up every verifier by 10 USDC (room 1.9 USDC, one case each) and
    /// writes checkpoint 2; returns the block whose hash redraws.
    function _newerCheckpoint() internal returns (uint256 randomBlock) {
        for (uint32 i = 1; i <= 14; i++) fairbind.topUpVerifierBond(i, 10_000_000);
        hv.roll(_now() + 1);
        require(fairbind.checkpointVerifierTree(PROFILE) == 2, "fixture: checkpoint 2");
        randomBlock = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
    }

    function _redraw(bytes32 n) internal {
        fairbind.assignVerifier(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.JUDGING), "fixture: redrawn to judging");
    }

    function _finalizePass(bytes32 n) internal {
        uint64 gate = fairbind.getCase(n).randomBlock;
        if (_now() <= gate) hv.roll(uint256(gate) + 1);
        hv.setBlockhash(gate, keccak256(abi.encode("gate", n)));
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.FINAL) && c.finalVerdict == uint8(FairBindCore.Verdict.PASS), "PASS");
    }

    /// e (block 10), a (block 20), w (block 30) are sampled and their cases
    /// wait for an assignment. a's sample receipt is never posted, so a ends
    /// UNSERVED while w still waits: s_f = 20. w is held by its wait and by the
    /// freeze; after the wait ends in a PASS it is frozen and claimable, never
    /// released; e, which waited too, is released on its schedule.
    function scenarioWaitingSaleFrozen(string memory settlement) external {
        _deployModules(_modules(SETTLEMENT, settlement), _waitProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 a = _purchase(G);
        hv.roll(30);
        bytes32 w = _purchase(G);
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = e;
        ns[1] = a;
        ns[2] = w;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 3, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        for (uint256 i; i < 3; i++) {
            fairbind.openSample(ns[i]);
            require(fairbind.getCase(ns[i]).state == WAITING, "fixture: every case waits");
        }
        _postReceipt(e);
        _postReceipt(w);
        hv.roll(uint256(fairbind.getSampleReceiptDue(a)) + 1);
        require(fairbind.getCase(w).state == WAITING, "fixture: w waits at the failure");
        fairbind.timeoutSampleReceipt(a);
        uint64 failureBlock = uint64(_now());
        FairBindCore.BondView memory b = _bond();
        require(fairbind.getCase(a).state == uint8(FairBindCore.CaseState.UNSERVED), "a unserved");
        require(b.freezeState == CLAIM_OPEN, "claim window open");
        require(fairbind.purchaseState(w) == HELD, "waiting item held");
        require(_releaseReverts(w, FairBindCore.InvalidTransition.selector), "waiting item not released");
        require(_claimReverts(w, FairBindCore.InvalidTransition.selector), "waiting item not yet claimable");
        // The wait ends: both waiting cases are redrawn on checkpoint 2 and pass.
        uint256 rb = _newerCheckpoint();
        hv.roll(rb + 1);
        hv.setBlockhash(rb, keccak256("redraw"));
        _redraw(e);
        _redraw(w);
        _judge(e, uint8(FairBindCore.Verdict.PASS));
        _judge(w, uint8(FairBindCore.Verdict.PASS));
        _finalizePass(e);
        _finalizePass(w);
        require(fairbind.getCase(w).state != WAITING && fairbind.getCase(e).state != WAITING, "no case waits");
        // Release conditions of e hold inside the claim window.
        hv.roll(uint256(b.claimUntilBlock));
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        (bool okE,) = address(this).call(abi.encodeCall(this.releaseExternal, (e)));
        require(okE, "earlier sale released");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "seller paid e");
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].from == 20 && spans[0].through == failureBlock, "window [s_f, failure]");
        require(fairbind.purchaseState(w) == FROZEN_CLAIMABLE, "waiting item frozen once judged");
        require(_releaseReverts(w, FairBindCore.FrozenEntry.selector), "waiting item still frozen after its wait");
        // After the window the frozen item is forfeited, not paid to the seller.
        hv.roll(uint256(b.claimUntilBlock) + 1);
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        hv.prank(KEEPER);
        fairbind.releasePurchase(w);
        require(fairbind.getPurchase(w).financialState == FORFEITED, "w forfeited");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "w never paid to the seller");
    }

    function test_waitingSaleAfterFailingSaleIsFrozen() public {
        this.scenarioWaitingSaleFrozen("");
    }

    function test_waitingSaleAfterFailingSaleIsFrozen_wholeFreezeMutantCaught() public {
        _expectMutantMessage(abi.encodeCall(this.scenarioWaitingSaleFrozen, (WHOLE_SETTLEMENT)), "earlier sale released");
    }

    // ------------------------------------------- 3. claims before the window

    /// e (block 10) and e1 (block 19) lie before s_f = 20; d2 (block 20, after
    /// d) and l (block 30) lie in the window and carry different amounts. A
    /// claim of e or e1 reverts ReceiptOutOfWindow; d2 and l pay their own
    /// amounts once, from the frozen pool.
    function scenarioClaimBeforeWindow(string memory delivery) external {
        _deployModules(_modules(DELIVERY, delivery), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(19);
        bytes32 e1 = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        bytes32 d2 = _purchase(H);
        hv.roll(30);
        bytes32 l = _purchase(G / 2);
        _unserved(d);
        require(_bond().freezeState == CLAIM_OPEN, "claim window open");
        require(_claimReverts(e, FairBindCore.ReceiptOutOfWindow.selector), "entry before s_f not claimable");
        require(_claimReverts(e1, FairBindCore.ReceiptOutOfWindow.selector), "entry at s_f - 1 not claimable");
        _anchorAndSealUnsampled(0, _list(e, e1, d, d2, l));
        // Also with an inclusion proof once anchored.
        require(_claimReverts(e, FairBindCore.ReceiptOutOfWindow.selector), "anchored entry before s_f not claimable");
        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 claimedBefore = _bond().claimedTotal;
        this.claimProvedExternal(d2);
        require(token.balanceOf(buyer) == buyerBefore + H, "d2 paid its amount");
        this.claimProvedExternal(l);
        require(token.balanceOf(buyer) == buyerBefore + H + G / 2, "l paid its amount");
        require(_bond().claimedTotal == claimedBefore + H + G / 2, "claimed total");
        require(fairbind.getPurchase(d2).financialState == REFUNDED, "d2 refunded");
        require(fairbind.getPurchase(l).financialState == REFUNDED, "l refunded");
        require(_claimReverts(l, FairBindCore.AlreadyClaimed.selector), "one claim per entry");
        require(fairbind.getPurchase(e).financialState == DEFERRED, "e untouched");
        require(fairbind.getPurchase(e1).financialState == DEFERRED, "e1 untouched");
    }

    function test_claimRefundRejectsEntryBeforeWindow() public {
        this.scenarioClaimBeforeWindow("");
    }

    function test_claimRefundRejectsEntryBeforeWindow_wholeFreezeMutantCaught() public {
        _expectMutantMessage(abi.encodeCall(this.scenarioClaimBeforeWindow, (WHOLE_DELIVERY)), "entry before s_f not claimable");
    }

    // ------------------------------------------------ 4. itemized forfeiture

    /// e (block 10) stays unreleased before the window; d (block 20) fails,
    /// l1 (block 30) is claimed, l2 (block 30, amount H) is not. The close
    /// takes nothing at once and leaves the deferred balance as it is; l2 is
    /// forfeited and locked when releasePurchase touches it; e is paid to the
    /// seller on its schedule.
    function scenarioForfeitItemized(string memory delivery) external {
        _deployModules(_modules(DELIVERY, delivery), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(30);
        bytes32 l1 = _purchase(G);
        bytes32 l2 = _purchase(H);
        _unserved(d);
        fairbind.claimRefund(d);
        _anchorAndSealUnsampled(0, _list(e, d, l1, l2));
        this.claimProvedExternal(l1);
        FairBindCore.BondView memory b = _bond();
        require(b.deferredBalance == G + H, "fixture: e and l2 deferred");
        hv.roll(uint256(b.claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 forfeitedBefore = b.forfeitedTotal;
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        require(fairbind.getLockedForfeit() == lockedBefore, "nothing taken at close");
        b = _bond();
        require(b.deferredBalance == G + H && b.forfeitedTotal == forfeitedBefore, "deferred balance kept");
        require(b.freezeState == CLAIM_CLOSED, "window closed");
        FairBindCore.ForfeitWindow[] memory windows = fairbind.getForfeitWindows(_bondId());
        require(windows.length == 1 && windows[0].itemized && windows[0].from == 20, "one itemized window from s_f");
        require(fairbind.purchaseState(l2) == FORFEITED, "l2 reported forfeited");
        require(fairbind.purchaseState(e) == DEFERRED, "e not forfeited");
        require(fairbind.purchaseState(l1) == REFUNDED, "claimed entry stays refunded");
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        hv.prank(KEEPER);
        fairbind.releasePurchase(l2);
        require(fairbind.getPurchase(l2).financialState == FORFEITED, "l2 swept");
        require(fairbind.getLockedForfeit() == lockedBefore + H, "l2 locked");
        require(_bond().deferredBalance == G, "l2 left the deferred balance");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore, "l2 not paid to the seller");
        // A second touch takes nothing more.
        require(_releaseReverts(l2, FairBindCore.InvalidTransition.selector), "l2 terminal");
        hv.roll(uint256(fairbind.getPurchase(e).releaseBlock) > _now() ? uint256(fairbind.getPurchase(e).releaseBlock) : _now());
        hv.prank(KEEPER);
        fairbind.releasePurchase(e);
        require(fairbind.getPurchase(e).financialState == RELEASED, "e released");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "e paid to the seller");
        require(fairbind.getLockedForfeit() == lockedBefore + H && _bond().deferredBalance == 0, "only l2 forfeited");
    }

    function test_forfeitItemizedWhenEarlierEntryUnreleased() public {
        this.scenarioForfeitItemized("");
    }

    function test_forfeitItemizedWhenEarlierEntryUnreleased_wholeFreezeMutantCaught() public {
        _expectMutantMessage(abi.encodeCall(this.scenarioForfeitItemized, (WHOLE_DELIVERY)), "nothing taken at close");
    }

    // ------------------------------------------------ 5. one-sum forfeiture

    /// d (block 10) is the account's first entry and fails; l1 (block 20) is
    /// claimed; l2 (block 30, amount H) and l3 (block 30, amount G / 2) are
    /// not. The close takes the unclaimed H + G / 2 as one sum and empties the
    /// deferred balance; neither entry is paid to the seller later.
    function test_forfeitOneSumWhenWindowAlone() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 d = _purchase(G);
        hv.roll(20);
        bytes32 l1 = _purchase(G);
        hv.roll(30);
        bytes32 l2 = _purchase(H);
        bytes32 l3 = _purchase(G / 2);
        _unserved(d);
        fairbind.claimRefund(d);
        _anchorAndSealUnsampled(0, _list(d, l1, l2, l3));
        this.claimProvedExternal(l1);
        FairBindCore.BondView memory b = _bond();
        require(b.deferredBalance == H + G / 2, "fixture: l2 and l3 deferred");
        hv.roll(uint256(b.claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        b = _bond();
        require(fairbind.getLockedForfeit() == lockedBefore + H + G / 2, "unclaimed taken as one sum");
        require(b.deferredBalance == 0 && b.freezeState == CLAIM_CLOSED, "deferred balance emptied");
        FairBindCore.ForfeitWindow[] memory windows = fairbind.getForfeitWindows(_bondId());
        require(windows.length == 1 && !windows[0].itemized && windows[0].from == 10, "one window, not itemized");
        require(fairbind.purchaseState(l2) == FORFEITED && fairbind.purchaseState(l3) == FORFEITED, "reported forfeited");
        require(fairbind.purchaseState(l1) == REFUNDED, "claimed entry refunded");
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        hv.prank(KEEPER);
        fairbind.releasePurchase(l2);
        hv.prank(KEEPER);
        fairbind.releasePurchase(l3);
        require(token.balanceOf(SELLER_OWNER) == ownerBefore, "not paid to the seller");
        require(fairbind.getLockedForfeit() == lockedBefore + H + G / 2, "taken once");
    }

    /// The one-sum close is decided by deferredFloor, the first settlement
    /// after the deferred balance was last empty (ADR 0030, 4), not by the
    /// entries the balance holds at the close. An earlier entry released
    /// before the close leaves the floor below the window, so the window
    /// closes itemized although no earlier entry is unreleased; the amount
    /// taken in the end is the same.
    function test_forfeitAfterEarlierEntryReleasedClosesItemizedWithTheSameAmount() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(30);
        bytes32 l = _purchase(H);
        _unserved(d);
        fairbind.claimRefund(d);
        _anchorAndSealUnsampled(0, _list(e, d, l));
        hv.roll(uint256(fairbind.getPurchase(e).releaseBlock));
        fairbind.releasePurchase(e);
        FairBindCore.BondView memory b = _bond();
        require(fairbind.getPurchase(e).financialState == RELEASED, "e released before the close");
        hv.roll(uint256(b.claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 deferredBefore = b.deferredBalance;
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        require(fairbind.getForfeitWindows(_bondId())[0].itemized, "closes itemized");
        require(fairbind.getLockedForfeit() == lockedBefore, "nothing taken at close");
        hv.prank(KEEPER);
        fairbind.releasePurchase(l);
        require(fairbind.getLockedForfeit() == lockedBefore + H, "l locked when touched");
        require(_bond().deferredBalance == deferredBefore - H, "l left the deferred balance");
    }
}
