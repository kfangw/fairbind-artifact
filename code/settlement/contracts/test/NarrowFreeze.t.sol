// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { WholeFreezeDelivery, WholeFreezePublication, WholeFreezeReview } from "./NarrowFreezeMutants.sol";

/// ADR 0030 (design 2 rule D2-6): a confirmed failure tied to the purchase
/// settled in block c freezes only the unreleased entries settled from c on;
/// earlier entries keep their release schedule. A later failure with an
/// earlier c lowers the start, whatever the seller's status; one tied to an
/// entry settled after a reinstatement adds a span. Each scenario that shows
/// the narrow window is run on a mutation build that freezes from block zero,
/// the rule of ADR 0012, and must fail there.
contract NarrowFreezeTest is ModuleSwapBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant SHARE = uint256(10_000_000) / 3;
    uint8 internal constant DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);
    uint8 internal constant FROZEN_CLAIMABLE = uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE);
    uint8 internal constant RELEASED = uint8(FairBindCore.FinancialState.RELEASED);
    uint8 internal constant REFUNDED = uint8(FairBindCore.FinancialState.REFUNDED);
    uint8 internal constant FORFEITED = uint8(FairBindCore.FinancialState.FORFEITED);
    uint8 internal constant CLAIM_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);
    uint8 internal constant CLAIM_CLOSED = uint8(FairBindCore.FreezeState.CLAIM_CLOSED);
    uint8 internal constant SUSPENDED = uint8(FairBindCore.SellerStatus.SUSPENDED);
    address internal constant KEEPER = address(0x4EE9E2);

    function _modules(uint256 index, string memory name) internal pure returns (string[10] memory names) {
        names = _productionModules();
        if (bytes(name).length != 0) names[index] = name;
    }

    function _three(bytes32 a, bytes32 b, bytes32 c) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](3);
        ns[0] = a;
        ns[1] = b;
        ns[2] = c;
    }

    function _one(bytes32 a) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](1);
        ns[0] = a;
    }

    // ------------------------------------------------- (a) 1, 2: from the sale

    /// Purchases e, d, l settle in blocks 10, 20, 30; d ends UNSERVED. Returns
    /// whether e, settled before d, is released on its own schedule while the
    /// claim window of d's failure is open; also checks the frozen side.
    function _earlierEntryKeepsItsSchedule(string memory delivery) internal returns (bool) {
        _deployModules(_modules(DELIVERY, delivery), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(30);
        bytes32 l = _purchase(G);
        _unserved(d);
        FairBindCore.BondView memory b = _bond();
        require(b.freezeState == CLAIM_OPEN && fairbind.getSeller(sellerId).status == SUSPENDED, "frozen and suspended");
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].through == _now(), "one span to the failure block");
        // The later entry is held and claimable.
        require(fairbind.purchaseState(l) == FROZEN_CLAIMABLE, "later entry frozen");
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        this.releaseExternal(l);
        _anchorAndSealUnsampled(0, _three(e, d, l));
        hv.roll(uint256(fairbind.getPurchase(e).releaseBlock));
        require(_now() <= b.claimUntilBlock, "fixture: inside the claim window");
        if (fairbind.purchaseState(e) != DEFERRED) return false;
        (bool ok,) = address(this).call(abi.encodeCall(this.releaseExternal, (e)));
        if (!ok) return false;
        require(fairbind.getPurchase(e).financialState == RELEASED, "released");
        // The earlier entry was never claimable; the later one is.
        _claimWith(l, _proof(l));
        require(fairbind.getPurchase(l).financialState == REFUNDED, "later entry claimed");
        return spans[0].from == fairbind.getPurchase(d).settledBlock;
    }

    function test_failureFreezesFromItsSaleAndEarlierEntriesKeepTheirSchedule() public {
        require(_earlierEntryKeepsItsSchedule(""), "narrow freeze");
    }

    function test_mutationFreezingFromZeroIsCaught() public {
        require(!_earlierEntryKeepsItsSchedule("NarrowFreezeMutants.sol:WholeFreezeDelivery"), "mutation caught");
    }

    /// An entry settled before the failing sale is outside the claim window.
    function test_earlierEntryIsNotClaimable() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        _unserved(d);
        require(fairbind.purchaseState(e) == DEFERRED, "not frozen");
        hv.expectRevert(FairBindCore.ReceiptOutOfWindow.selector);
        this.claimExternal(e, _emptyProof());
        // The failing purchase is refunded through its own case.
        fairbind.claimRefund(d);
        require(fairbind.getPurchase(d).financialState == REFUNDED, "refunded");
    }

    // ------------------------------------------ (a) 3, 4: later failures lower

    /// A second failure of the suspended account, tied to an earlier sale,
    /// lowers the start of the window to that sale and freezes what lies
    /// between; the end moves to the second failure.
    function test_laterFailureWithAnEarlierSaleLowersTheStart() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(81);
        _disputeNonDelivery(e);
        _disputeNonDelivery(d);
        hv.roll(uint256(fairbind.getCase(d).serveDue) + 1);
        fairbind.timeoutServe(d);
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].from == 20, "starts at d");
        hv.roll(_now() + 1);
        require(fairbind.getSeller(sellerId).status == SUSPENDED, "already suspended");
        hv.prank(KEEPER);
        fairbind.timeoutServe(e);
        spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].from == 10 && spans[0].through == _now(), "lowered to e, end moved");
        FairBindCore.BondView memory b = _bond();
        require(b.failureCount == 2 && b.freezeBlock == _now(), "counted, window end moved");
    }

    /// A failure tied to an entry settled after a reinstatement adds a span
    /// from that entry's sale: an entry settled after the reinstatement but
    /// before that sale stays outside, while the first window keeps its entries.
    function test_failureAfterReinstatementAddsASpanFromItsSale() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 w = _purchase(G);
        bytes32 d = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        uint64 firstEnd = _bond().freezeBlock;
        token.mint(SELLER_OWNER, SHARE);
        hv.startPrank(SELLER_OWNER);
        fairbind.topUpBond(_bondId(), uint128(SHARE));
        fairbind.reinstateSeller(sellerId);
        hv.stopPrank();
        hv.roll(_now() + 60);
        bytes32 x = _purchase(G);
        hv.roll(_now() + 40);
        bytes32 y = _purchase(G);
        _unserved(y);
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 2, "two spans");
        require(spans[0].from == 10 && spans[0].through == firstEnd, "first window kept");
        require(spans[1].from == fairbind.getPurchase(y).settledBlock && spans[1].through == _now(), "span from y");
        require(fairbind.purchaseState(w) == FROZEN_CLAIMABLE, "first window entry frozen");
        require(fairbind.purchaseState(x) == DEFERRED, "entry between the spans keeps its schedule");
        hv.expectRevert(FairBindCore.ReceiptOutOfWindow.selector);
        this.claimExternal(x, _emptyProof());
        // x is not frozen: its release waits only for its epoch's value.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.releaseExternal(x);
        // Two spans close itemized: nothing is taken as one sum.
        hv.roll(uint256(_bond().claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        hv.prank(KEEPER);
        fairbind.forfeitUnclaimed(_bondId());
        require(_bond().freezeState == CLAIM_CLOSED && fairbind.getLockedForfeit() == lockedBefore, "closed itemized");
        FairBindCore.ForfeitWindow[] memory windows = fairbind.getForfeitWindows(_bondId());
        require(windows.length == 2 && windows[0].itemized && windows[1].itemized, "both windows itemized");
        require(fairbind.purchaseState(w) == FORFEITED && fairbind.purchaseState(x) == DEFERRED, "w forfeited, x not");
        uint256 deferredBefore = _bond().deferredBalance;
        hv.prank(KEEPER);
        fairbind.releasePurchase(w);
        require(fairbind.getPurchase(w).financialState == FORFEITED, "swept");
        require(_bond().deferredBalance == deferredBefore - G && fairbind.getLockedForfeit() == lockedBefore + G, "locked");
    }

    // --------------------------------------------- forfeiture of the window

    /// When the failing sale is the account's earliest unreleased entry, the
    /// window closes as one sum as before (ADR 0022).
    function test_windowWithoutEarlierEntriesForfeitsOneSum() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 d = _purchase(G);
        hv.roll(20);
        bytes32 l = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        hv.roll(uint256(_bond().claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        fairbind.forfeitUnclaimed(_bondId());
        FairBindCore.BondView memory b = _bond();
        require(b.deferredBalance == 0 && fairbind.getLockedForfeit() == lockedBefore + G, "one sum");
        require(!fairbind.getForfeitWindows(_bondId())[0].itemized, "not itemized");
        require(fairbind.purchaseState(l) == FORFEITED, "forfeited");
    }

    /// With an earlier unreleased entry the window closes itemized: the
    /// earlier entry is released on schedule and the frozen one is forfeited
    /// when it is touched.
    function test_windowWithAnEarlierEntryClosesItemized() public {
        _deployModules(_productionModules(), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(30);
        bytes32 l = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        _anchorAndSealUnsampled(0, _three(e, d, l));
        hv.roll(uint256(_bond().claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        fairbind.forfeitUnclaimed(_bondId());
        require(fairbind.getForfeitWindows(_bondId())[0].itemized, "itemized");
        require(fairbind.getLockedForfeit() == lockedBefore && _bond().deferredBalance == 2 * G, "nothing taken yet");
        require(fairbind.purchaseState(l) == FORFEITED && fairbind.purchaseState(e) == DEFERRED, "states");
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(e);
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "earlier entry paid to the seller");
        fairbind.releasePurchase(l);
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "frozen entry not paid");
        require(_bond().deferredBalance == 0 && fairbind.getLockedForfeit() == lockedBefore + G, "frozen entry locked");
    }

    // ---------------------------------------------------- missed anchor

    /// A missed anchor freezes from the first block of its epoch: an entry of
    /// an earlier epoch keeps its schedule. Keeper calls from a third address.
    function _missedAnchorKeepsEarlierEpoch(string memory publication) internal returns (bool) {
        _deployModules(_modules(PUBLICATION, publication), _productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(310);
        bytes32 m = _purchase(G);
        _buildTree(_one(e));
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(1001);
        hv.prank(KEEPER);
        fairbind.timeoutAnchor(sellerId, 1);
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        require(spans.length == 1 && spans[0].through == 1001, "frozen at the timeout");
        hv.prank(KEEPER);
        fairbind.claimEpochFailure(m);
        uint64 rb = fairbind.getAnchor(sellerId, 0).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, _unsampledBeacon(0, _one(e)));
        hv.prank(KEEPER);
        fairbind.seal(sellerId, 0);
        hv.roll(uint256(fairbind.getPurchase(e).releaseBlock));
        (bool ok,) = address(this).call(abi.encodeCall(this.releaseExternal, (e)));
        return ok && spans[0].from == 301;
    }

    function test_missedAnchorFreezesFromItsEpoch() public {
        require(_missedAnchorKeepsEarlierEpoch(""), "narrow freeze");
    }

    function test_missedAnchorMutationIsCaught() public {
        require(!_missedAnchorKeepsEarlierEpoch("NarrowFreezeMutants.sol:WholeFreezePublication"), "mutation caught");
    }

    // -------------------------------------- (b) inconclusive above threshold

    /// The freeze of an inconclusive window above its threshold starts at the
    /// sale of the window's first inconclusive case.
    function _inconclusiveFreezeStartsAtItsSale(string memory review) internal returns (bool) {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.maxInconclusivePpm = 1;
        p.minJudgedCount = 1;
        string[10] memory names = _productionModules();
        if (bytes(review).length != 0) names[7] = review;
        _deployModules(names, p);
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 n = _purchase(G);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = e;
        ns[1] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 2, keccak256("publication"));
        uint64 rb = fairbind.getAnchor(sellerId, 0).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        fairbind.openSample(n);
        _judge(n, uint8(FairBindCore.Verdict.INCONCLUSIVE));
        uint64 caseRandom = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(caseRandom) + 1);
        hv.setBlockhash(caseRandom, keccak256("candidate"));
        fairbind.finalizeCase(n);
        FairBindCore.BondView memory b = _bond();
        require(b.freezeState == CLAIM_OPEN && b.failureCount == 0, "frozen, not counted");
        require(fairbind.purchaseState(n) == FROZEN_CLAIMABLE, "its own sale frozen");
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(_bondId());
        return spans[0].from == 20 && fairbind.purchaseState(e) == DEFERRED;
    }

    function test_inconclusiveFreezeStartsAtTheFirstInconclusiveSale() public {
        require(_inconclusiveFreezeStartsAtItsSale(""), "narrow freeze");
    }

    function test_inconclusiveMutationIsCaught() public {
        require(!_inconclusiveFreezeStartsAtItsSale("NarrowFreezeMutants.sol:WholeFreezeReview"), "mutation caught");
    }
}
