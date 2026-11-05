// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeShared } from "../src/modules/ExchangeShared.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";

/// The judgment of a proof profile (ADR 0037, rules D2-28 to D2-33): the
/// sample case and the buyer's dispute wait T_p for a PASS proof the
/// contract checks; the seller's proof on a frozen entry is released after
/// the receipt-binding window.
contract PassProofTest is ExchangeBase {
    uint8 internal constant FINAL = uint8(FairBindCore.CaseState.FINAL);
    uint8 internal constant PROOF_WAIT = uint8(FairBindCore.CaseState.PROOF_WAIT);
    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant HELD = uint8(FairBindCore.FinancialState.HELD);
    uint8 internal constant RELEASABLE = uint8(FairBindCore.FinancialState.RELEASABLE);
    uint8 internal constant REFUNDABLE = uint8(FairBindCore.FinancialState.REFUNDABLE);
    uint8 internal constant NON_DELIVERY = uint8(FairBindCore.CaseTrigger.NON_DELIVERY);
    uint8 internal constant WRONG_DELIVERY = uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY);
    uint256 internal constant D0 = 5_000_000;

    function buyExternal(uint256 value, uint256 age) external returns (bytes32) {
        return _buy(value, age);
    }

    function _start() internal {
        _deployDefault();
        hv.roll(10);
    }

    // ------------------------------------------------------- sample case

    function test_honestSaleIsBoundProvedAndReleased() public {
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        require(_bound(n), "bound by the anchor deadline");
        fx.openProofSample(n);
        require(_state(n) == PROOF_WAIT && _fs(n) == HELD, "the case waits for its proof");
        require(fairbind.getCase(n).judgeDue == _now() + 300, "T_p");
        _prove(n, 0);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == PASS, "PASS");
        require(_fs(n) == RELEASABLE && _record(n).proven, "releasable, proven");
        hv.roll(uint256(fairbind.getPurchase(n).settledBlock) + 40_000);
        uint256 before = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(n);
        require(token.balanceOf(SELLER_OWNER) == before + 10_000, "paid");
    }

    function test_noProofByTheDeadlineIsAConfirmedFailure() public {
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        fx.openProofSample(n);
        uint64 due = fairbind.getCase(n).judgeDue;
        hv.roll(due);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fx.timeoutProof(n);
        hv.roll(uint256(due) + 1);
        // A proof after the deadline is kept for the purchase but no longer
        // ends the case.
        ExchangeStore.PassProof memory q = _passProof(n);
        fx.prove(n, 0, q);
        require(_state(n) == PROOF_WAIT && _record(n).proven, "the case still waits");
        fx.timeoutProof(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "FAIL");
        require(_fs(n) == REFUNDABLE, "refundable");
        FairBindCore.BondView memory b = _bond();
        require(b.failureCount == 1, "counted");
        require(b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        uint256 before = token.balanceOf(buyer);
        fairbind.claimRefund(n);
        require(token.balanceOf(buyer) == before + 10_000, "refunded");
    }

    function test_absentInputFailsBeforeTheDeadline() public {
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        fx.openProofSample(n);
        uint64 t = _record(n).refTime;
        bytes memory inWindow = _update(t + 10, t - 1, PRICE);
        bytes memory late = _update(t + 11, t - 1, PRICE);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fx.proveAbsence(n, inWindow);
        // The first update after t was published past t + max_skew.
        fx.proveAbsence(n, late);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "FAIL on the absent input");
        require(_bond().failureCount == 1, "counted");
    }

    function test_theProofChecksEveryInput() public {
        _start();
        bytes32 n = _buy();
        bytes32 m = _buy();
        _bindAndSeal(_two(n, m));
        fx.openProofSample(n);
        fx.openProofSample(m);
        uint64 t = _record(n).refTime;
        ExchangeStore.PassProof memory q = _passProof(n);
        // Not the first update after t, or one before t.
        q.update = _update(t + 2, t, PRICE);
        hv.expectRevert(MockUniquePriceFeed.BadUpdate.selector);
        this.proveExternal(n, 0, q);
        q.update = _update(t - 1, t - 3, PRICE);
        hv.expectRevert(MockUniquePriceFeed.BadUpdate.selector);
        this.proveExternal(n, 0, q);
        // An update of the window but a response off by 0.2 %.
        q.update = _update(t + 2, t - 1, PRICE / 1000 * 1002);
        hv.expectRevert(ExchangeShared.ProofNotPass.selector);
        this.proveExternal(n, 0, q);
        // A key that is not the signed one.
        q = _passProof(n);
        q.ek = keccak256("another key");
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.proveExternal(n, 0, q);
        // Appended call data.
        q = _passProof(n);
        (bool ok, bytes memory ret) = address(fairbind).call(
            abi.encodePacked(abi.encodeWithSelector(fx.prove.selector, n, uint8(0), q), bytes32(0))
        );
        require(!ok && bytes4(ret) == FairBindCore.NonCanonical.selector, "appended bytes refused");
        // An early FAIL with a proof that passes, and an unknown flag.
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.proveExternal(n, 2, q);
        hv.expectRevert(ExchangeShared.ProofNotAllowed.selector);
        this.proveExternal(n, 1, q);
        this.proveExternal(n, 0, q);
        hv.expectRevert(ExchangeShared.ProofNotAllowed.selector);
        this.proveExternal(n, 0, q);
        // The canonical input fails the predicate: anyone ends m early.
        ExchangeStore.PassProof memory f = _passProof(m);
        uint64 tm = _record(m).refTime;
        f.update = _update(tm + 2, tm - 1, PRICE / 1000 * 1002);
        hv.prank(buyer);
        fx.prove(m, 2, f);
        require(fairbind.getCase(m).finalVerdict == FAIL, "FAIL before the deadline");
    }

    function test_staleAuthorizationIsRefused() public {
        require(_staleRefused(""), "refused");
    }

    function test_staleAuthorizationAcceptedIsCaught() public {
        require(!_staleRefused("ExchangeMutants.sol:StaleRefSettlement"), "mutation caught");
    }

    function _staleRefused(string memory settlement) internal returns (bool) {
        moduleNames[1] = settlement;
        _start();
        this.buyExternal(10_000, 120);
        try this.buyExternal(10_000, 121) returns (bytes32) {
            return false;
        } catch (bytes memory err) {
            return bytes4(err) == FairBindCore.AuthorizationExpired.selector;
        }
    }

    function test_honestProofPasses() public {
        require(_honestPasses(""), "passes");
    }

    function test_keyStreamWithoutTheNonceIsCaught() public {
        require(!_honestPasses("ExchangeMutants.sol:NoNonceProof"), "mutation caught");
    }

    function _honestPasses(string memory pass) internal returns (bool) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        fx.openProofSample(n);
        try this.proveExternal(n, 0, _passProof(n)) {
            return fairbind.getCase(n).finalVerdict == PASS;
        } catch {
            return false;
        }
    }

    function test_plaintextWithoutItsPadMarkIsRefused() public {
        require(_unmarkedRefused(""), "refused");
    }

    function test_unpadWithoutTheMarkIsCaught() public {
        require(!_unmarkedRefused("ExchangeMutants.sol:NoMarkProof"), "mutation caught");
    }

    /// The seller commits a plaintext whose pad lacks the 0x80 mark.
    function _unmarkedRefused(string memory pass) internal returns (bool) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _start();
        bytes32 n = _buy();
        bytes memory padded = new bytes(64);
        for (uint256 i; i < RESPONSE.length; i++) padded[i] = RESPONSE[i];
        Bundle memory b = _bundleWith(n, keccak256("ek"), padded, fx.proofCommitment(n));
        leafOf[n] = b.leaf;
        bundleOf[n] = b;
        _bindAndSeal(_one(n));
        fx.openProofSample(n);
        try this.proveExternal(n, 0, _passProof(n)) {
            return false;
        } catch (bytes memory err) {
            return bytes4(err) == FairBindCore.InvalidProof.selector;
        }
    }

    // ----------------------------------------------------------- disputes

    function test_keyDisputePaysTheMeasuredCostAndReturnsTheRest() public {
        (uint256 share, uint256 back) = _keyDisputeShare("");
        require(share != 0 && share < 401_200, "measured, below c_key");
        require(back == D0 - share, "the rest goes back");
    }

    function test_constantKeyShareIsCaught() public {
        (uint256 share,) = _keyDisputeShare("ExchangeMutants.sol:CapShareProof");
        require(share == 401_200, "mutation caught");
    }

    function _keyDisputeShare(string memory pass) internal returns (uint256 share, uint256 back) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        uint256 b0 = token.balanceOf(buyer);
        hv.prank(buyer);
        fx.openProofDispute(n, NON_DELIVERY);
        require(token.balanceOf(buyer) == b0 - D0 && _fs(n) == HELD, "deposit taken, entry held");
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        b0 = token.balanceOf(buyer);
        _prove(n, 0);
        share = token.balanceOf(SELLER_OWNER) - s0;
        back = token.balanceOf(buyer) - b0;
        require(_record(n).disputeState == ExchangeStore.DISPUTE_PASSED && _fs(n) == RELEASABLE, "passed");
    }

    /// The gas price of the transaction does not enter the measured share.
    function test_priorityFeeDoesNotRaiseTheShare() public {
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        hv.prank(buyer);
        fx.openProofDispute(n, NON_DELIVERY);
        ExchangeStore.PassProof memory q = _passProof(n);
        uint256 snap = sw.snapshotState();
        xv.txGasPrice(1_000_000_000_000);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        fx.prove(n, 0, q);
        uint256 high = token.balanceOf(SELLER_OWNER) - s0;
        sw.revertToState(snap);
        xv.txGasPrice(BASEFEE);
        s0 = token.balanceOf(SELLER_OWNER);
        fx.prove(n, 0, q);
        uint256 low = token.balanceOf(SELLER_OWNER) - s0;
        require(high == low && high != 0, "same share");
    }

    /// The seller withholds the key: the dispute refunds the purchase and
    /// counts nothing; its sample case still opens and is judged.
    function test_withheldKeyRefundsAndTheSampleCaseStays() public {
        _start();
        bytes32 n = _buy();
        bytes32 m = _buy();
        _postSigned(n);
        _postSigned(m);
        hv.prank(buyer);
        fx.openProofDispute(n, NON_DELIVERY);
        hv.prank(buyer);
        fx.openProofDispute(m, NON_DELIVERY);
        hv.roll(_record(n).disputeDue + 1);
        uint256 b0 = token.balanceOf(buyer);
        fx.timeoutProof(n);
        fx.timeoutProof(m);
        require(token.balanceOf(buyer) == b0 + 2 * D0, "deposits back");
        require(_fs(n) == REFUNDABLE && _fs(m) == REFUNDABLE, "refunds due");
        require(_bond().failureCount == 0, "no failure");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "active");
        fairbind.claimRefund(n);
        _anchorX(0, _two(n, m));
        _matchAll(_two(n, m));
        _sealX(0);
        fx.openProofSample(n);
        fx.openProofSample(m);
        _prove(n, 0);
        require(fairbind.getCase(n).finalVerdict == PASS, "n passes its sample case");
        hv.roll(fairbind.getCase(m).judgeDue + 1);
        b0 = token.balanceOf(buyer);
        fx.timeoutProof(m);
        require(fairbind.getCase(m).finalVerdict == FAIL && _bond().failureCount == 1, "m fails, counted");
        fairbind.claimRefund(m);
        require(token.balanceOf(buyer) == b0 + 10_000, "one refund");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimRefund(m);
    }

    function test_disputeOfAProvenPurchasePassesAtOnce() public {
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        fx.openProofSample(n);
        _prove(n, 0);
        uint256 b0 = token.balanceOf(buyer);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        hv.prank(buyer);
        fx.openProofDispute(n, NON_DELIVERY);
        require(_record(n).disputeState == ExchangeStore.DISPUTE_PASSED, "passed at once");
        require(token.balanceOf(buyer) == b0 && token.balanceOf(SELLER_OWNER) == s0, "share zero");
        require(_fs(n) == RELEASABLE, "back to its schedule");
    }

    function test_wrongDeliveryDisputeThatPassesPaysTheDeposit() public {
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        hv.prank(buyer);
        fx.openProofDispute(n, WRONG_DELIVERY);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        _prove(n, 0);
        require(token.balanceOf(SELLER_OWNER) == s0 + D0, "d0 to the seller");
    }

    // ------------------------------------------------ the seller's proof

    function test_selfProofReleasesAfterTheBindingWindow() public {
        require(_selfReleaseBoundaryHolds(""), "held at retainUntil, paid after");
    }

    function test_releaseAtTheBindingBoundIsCaught() public {
        require(!_selfReleaseBoundaryHolds("ExchangeMutants.sol:EarlyReleaseSelf"), "mutation caught");
    }

    /// a fails its sample case: the account freezes from a's sale. b, sold
    /// after a, passes its own case, is frozen and proved by the seller.
    function _selfReleaseBoundaryHolds(string memory selfMod) internal returns (bool) {
        if (bytes(selfMod).length != 0) selfArtifact = selfMod;
        _start();
        bytes32 a = _buy();
        hv.roll(11);
        bytes32 b = _buy();
        _bindAndSeal(_two(a, b));
        fx.openProofSample(a);
        fx.openProofSample(b);
        _prove(b, 0);
        hv.roll(fairbind.getCase(a).judgeDue + 1);
        fx.timeoutProof(a);
        require(_bond().freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window");
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(b);
        // Past the seal deadline and the open window of epoch 0 (1669 + 200).
        hv.roll(1870);
        hv.prank(SELLER_OWNER);
        fx.selfProve(b);
        require(_record(b).selfState == ExchangeStore.SELF_CONFIRMED && _fs(b) == HELD, "confirmed, held");
        FairBindCore.FairBindReceipt memory r;
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimRefund(b, r, "", _emptyProof());
        uint64 retain = fairbind.getPurchase(b).retainUntil;
        hv.roll(retain);
        try this.releaseSelfExternal(b) {
            return false;
        } catch { }
        hv.roll(uint256(retain) + 1);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        fx.releaseSelfProven(b);
        return token.balanceOf(SELLER_OWNER) == s0 + 10_000;
    }

    function releaseSelfExternal(bytes32 n) external {
        fx.releaseSelfProven(n);
    }

    function test_selfProofWaitsForTheAccountsOpenCases() public {
        _start();
        bytes32 a = _buy();
        hv.roll(11);
        bytes32 b = _buy();
        // c is never posted: it is refunded after A_0 and is no sale.
        bytes32 c = _buy();
        hv.roll(301);
        bytes32 d = _buy();
        _postSigned(a);
        _postSigned(b);
        _postSigned(d);
        bytes32[] memory e0 = new bytes32[](3);
        e0[0] = a;
        e0[1] = b;
        e0[2] = c;
        _anchorX(0, e0);
        _matchAll(_two(a, b));
        _anchorX(1, _one(d));
        _matchAll(_one(d));
        _sealX(0);
        fx.openProofSample(a);
        fx.openProofSample(b);
        _prove(b, 0);
        hv.expectRevert(FairBindCore.NotBound.selector);
        fx.openProofSample(c);
        fx.refundUnbound(c);
        hv.roll(fairbind.getCase(a).judgeDue + 1);
        fx.timeoutProof(a);
        _sealX(1);
        fx.openProofSample(d);
        hv.roll(1870);
        hv.prank(SELLER_OWNER);
        fx.selfProve(b);
        require(_record(b).selfState == ExchangeStore.SELF_RESERVED, "reserved while d is open");
        require(!fx.selfProofReady(b), "not ready");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fx.activateSelfProof(b);
        _prove(d, 0);
        fx.activateSelfProof(b);
        require(_record(b).selfState == ExchangeStore.SELF_CONFIRMED, "confirmed once d ended");
    }

    function test_selfProofConfirmedWhileACaseIsOpenIsCaught() public {
        selfArtifact = "ExchangeMutants.sol:EarlyReadySelf";
        _start();
        bytes32 a = _buy();
        hv.roll(11);
        bytes32 b = _buy();
        hv.roll(301);
        bytes32 d = _buy();
        _postSigned(a);
        _postSigned(b);
        _postSigned(d);
        _anchorX(0, _two(a, b));
        _matchAll(_two(a, b));
        _anchorX(1, _one(d));
        _matchAll(_one(d));
        _sealX(0);
        fx.openProofSample(a);
        fx.openProofSample(b);
        _prove(b, 0);
        hv.roll(fairbind.getCase(a).judgeDue + 1);
        fx.timeoutProof(a);
        _sealX(1);
        fx.openProofSample(d);
        hv.roll(1870);
        hv.prank(SELLER_OWNER);
        fx.selfProve(b);
        require(_record(b).selfState == ExchangeStore.SELF_CONFIRMED, "mutation caught");
    }

    function test_bindingFailureVoidsTheSelfProof() public {
        _start();
        bytes32 a = _buy();
        hv.roll(11);
        bytes32 b = _buy();
        _bindAndSeal(_two(a, b));
        fx.openProofSample(a);
        fx.openProofSample(b);
        _prove(b, 0);
        hv.roll(fairbind.getCase(a).judgeDue + 1);
        fx.timeoutProof(a);
        hv.roll(1870);
        hv.prank(SELLER_OWNER);
        fx.selfProve(b);
        require(_record(b).selfState == ExchangeStore.SELF_CONFIRMED, "confirmed");
        // Two receipts the seller signed for b.
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(b);
        FairBindCore.FairBindReceipt memory r1 =
            FairBindCore.FairBindReceipt(1, p.sellerId, p.profileId, b, p.requestHash, keccak256("r1"), CLAIMS, 0, p.epoch, 1);
        FairBindCore.FairBindReceipt memory r2 =
            FairBindCore.FairBindReceipt(1, p.sellerId, p.profileId, b, p.requestHash, keccak256("r2"), CLAIMS, 0, p.epoch, 1);
        fairbind.proveEquivocation(
            r1, _sig(SELLER_KEY, fairbind.receiptDigest(r1)), r2, _sig(SELLER_KEY, fairbind.receiptDigest(r2))
        );
        require(_record(b).selfState == ExchangeStore.SELF_INVALID, "void");
        require(_fs(b) == REFUNDABLE, "refunded");
    }
}
