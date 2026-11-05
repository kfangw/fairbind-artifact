// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockVrfVerifier } from "./MockVrfVerifier.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { IBatchedFairBind } from "./BatchInterfaces.sol";
// Keeps the mutation artifacts built when a filter selects only some tests.
import { AnyWindowRegistry } from "./BindStartMutants.sol";

/// Rule D2-19 (g), with the start of rule D2-19 (h) withdrawn: the binding proof
/// (proveMisanchoredReceipt) is taken from the anchor on, also before the
/// epoch's SAMPLE value, through the window. Rule D2-13 (c) checks 6
/// (T_keep >= F_max), 7 (the blocks from the epoch start to the end of the
/// value wait, plus the proof slack, fit in F_max) and 8 (L_F + marginBlocks
/// - 1 <= F_max <= T_hold - 1), the batched hold L_F + marginBlocks and the
/// keeper slack (6 * maxAssignments + 4) * keeperSlack <= marginBlocks - 1
/// and keeperSlack <= sealBlocks - 2. Rule 8.2 row 25: the
/// SAMPLE request does not depend on an anchor.
///
/// The deployment is the optional signature-free vote profile of ExchangeBase.
/// Epoch 0 runs from block 1 to 300 and its anchor deadline is A = 700. The
/// request-based source has D_V = 10 and T_V = 20, so D_S = 11, the value
/// block is A + 1 + D_S = 712 and M = A + D_S + T_V = 731. F_max = 30,008 and
/// T_keep = retentionBlocks = 40,000.
contract BindStartTest is ExchangeBase {
    uint64 internal constant A = 700;
    uint32 internal constant D_V = 10;
    uint32 internal constant T_V = 20;
    uint64 internal constant M = A + D_V + 1 + T_V;
    uint256 internal constant VRF_KEY = 0x5EED;
    uint8 internal constant SAMPLE = 1;
    address internal constant KEEPER = address(0x4EE9E2);
    uint32 internal constant F_MAX = 30_008;

    FairBindVrf internal vrf;

    struct Bind {
        bytes32 n;
        FairBindCore.FairBindReceipt receipt;
        bytes sig;
        bytes32 anchoredLeaf;
        FairBindCore.ReceiptProof proof;
        uint64 settled;
    }

    // ------------------------------------------------------------- helpers

    function _source() internal returns (FairBindVrf) {
        return new FairBindVrf(address(fairbind), new MockVrfVerifier(), abi.encode(hv.addr(VRF_KEY)), D_V, T_V);
    }

    /// The signature-free vote deployment with the request-based source set
    /// after activation (from block 2 on).
    function _setUpVrf() internal {
        mode = ExchangeStore.MODE_NONE;
        _deployDefault();
        vrf = _source();
        fairbind.setRandomness(address(vrf));
    }

    function _sampleId(uint24 e) internal pure returns (bytes32) {
        return keccak256(abi.encode(SAMPLE, abi.encode(uint32(PROFILE), uint64(A + 300 * uint256(e)))));
    }

    function _request(uint24 e) internal {
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, e);
    }

    function _fulfill(uint24 e) internal {
        bytes32 id = _sampleId(e);
        bytes memory proof = _sig(VRF_KEY, keccak256(vrf.storedAlpha(id)));
        bytes32 output = keccak256(abi.encode(MockVrfVerifier(address(vrf.verifier())).OUTPUT_DOMAIN(), proof));
        hv.prank(KEEPER);
        vrf.fulfill(id, output, proof);
    }

    /// Three purchases of epoch 0 anchored at block 600 with filler leaves:
    /// the anchored leaf at the middle nonce is not the receipt the seller
    /// signed for it.
    function _misanchored() internal returns (Bind memory b) {
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _buy();
        _anchorX(0, ns);
        b.n = xs[1];
        b.receipt = _receipt(b.n);
        b.sig = _sig(SELLER_KEY, fairbind.receiptDigest(b.receipt));
        b.anchoredLeaf = keccak256(abi.encode("filler", b.n));
        (uint32 index, bytes32[] memory siblings) = _xPath(b.n);
        b.proof = FairBindCore.ReceiptProof(index, 3, siblings);
        b.settled = fairbind.getPurchase(b.n).settledBlock;
    }

    function proveExternal(Bind memory b) external {
        fairbind.proveMisanchoredReceipt(b.receipt, b.sig, b.anchoredLeaf, b.proof);
    }

    function _prove(Bind memory b) internal {
        fairbind.proveMisanchoredReceipt(b.receipt, b.sig, b.anchoredLeaf, b.proof);
    }

    function _confirmed(Bind memory b) internal view {
        require(_fs(b.n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refundable");
        require(fairbind.getCase(b.n).trigger == uint8(FairBindCore.CaseTrigger.EQUIVOCATION), "equivocation");
    }

    // ------------------------------- D2-19 (g): taken from the anchor on

    /// No start at the SAMPLE value (rule D2-19 (h) withdrawn): the proof is
    /// taken in the anchor's block, before the SAMPLE request
    /// and before its value.
    function test_bindingProofBeforeTheValueIsTaken() public {
        _setUpVrf();
        Bind memory b = _misanchored();
        (bool ready,) = vrf.valueOf(_sampleId(0));
        require(!ready, "no value yet");
        _prove(b);
        _confirmed(b);
    }

    /// Also between the request and the value, in the value block.
    function test_bindingProofAfterTheRequestIsTaken() public {
        _setUpVrf();
        Bind memory b = _misanchored();
        hv.roll(A + 1);
        _request(0);
        hv.roll(A + 1 + D_V + 1);
        _prove(b);
        _confirmed(b);
    }

    /// The window end of (g): taken at s + F_max and at the purchase's
    /// retainUntil = s + T_keep, refused after it.
    function test_bindingProofHoldsThroughTheWindow() public {
        _setUpVrf();
        Bind memory b = _misanchored();
        uint256 snap = sw.snapshotState();
        hv.roll(uint256(b.settled) + F_MAX);
        _prove(b);
        _confirmed(b);
        sw.revertToState(snap);
        uint64 until = fairbind.getPurchase(b.n).retainUntil;
        require(until == b.settled + 40_000, "retainUntil = s + T_keep");
        hv.roll(until + 1);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.proveExternal(b);
        hv.roll(until);
        _prove(b);
        _confirmed(b);
    }

    /// The mutation build that waits for the SAMPLE value refuses the proof
    /// before the value and takes it once the value is stored.
    function test_bindingProofWaitingForTheValueIsCaught() public {
        moduleNames[RECOVERY] = "BindStartMutants.sol:ValueStartRecovery";
        _setUpVrf();
        Bind memory b = _misanchored();
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.proveExternal(b);
        hv.roll(A + 1);
        _request(0);
        hv.roll(A + 1 + D_V);
        _fulfill(0);
        _prove(b);
        _confirmed(b);
    }

    /// An exiting account (rule D2-19 (g)).
    function test_bindingProofOfAnExitingAccount() public {
        _setUpVrf();
        Bind memory b = _misanchored();
        hv.prank(SELLER_OWNER);
        fairbind.requestSellerExit(sellerId);
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.EXITING), "exiting");
        _prove(b);
        _confirmed(b);
    }

    // -------------------------------------------- D2-13 (c) checks 6 and 7

    function _accepts(ExchangeStore.Input memory x) internal returns (bool) {
        x.termsHash = fx.exchangeTermsHash(PROFILE, x);
        try fx.setExchangeTerms(PROFILE, x) {
            return true;
        } catch (bytes memory reason) {
            require(bytes4(reason) == FairBindCore.InvalidProfile.selector, "refused as a profile");
            return false;
        }
    }

    function activateExternal() external {
        fairbind.setServiceProfileActive(PROFILE, true);
    }

    function _activates() internal returns (bool) {
        try this.activateExternal() {
            return true;
        } catch (bytes memory reason) {
            require(bytes4(reason) == FairBindCore.InvalidProfile.selector, "refused as a profile");
            return false;
        }
    }

    /// Deploys the profile without terms and without activation.
    function _bare(uint8 m) internal {
        mode = m;
        skipActivation = true;
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(_exchangeProfile(), _input(m), false);
    }

    /// Check 6: F_max = 0 and F_max > T_keep are refused, F_max = T_keep is
    /// taken, for each mode.
    function test_keepBelowTheWindowIsRefused() public {
        uint8[3] memory modes = [ExchangeStore.MODE_NONE, ExchangeStore.MODE_VOTE_SIG, ExchangeStore.MODE_PROOF];
        for (uint256 i; i < 3; i++) {
            _bare(modes[i]);
            ExchangeStore.Input memory x = _input(modes[i]);
            x.bindWindow = 0;
            require(!_accepts(x), "empty window");
            x.bindWindow = 40_001;
            require(!_accepts(x), "window above T_keep");
            x.bindWindow = 40_000;
            require(_accepts(x), "window = T_keep");
        }
    }

    function test_keepBelowTheWindowAcceptedIsCaught() public {
        exchangeArtifact = "BindStartMutants.sol:ShortKeepExchange";
        _bare(ExchangeStore.MODE_NONE);
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_NONE);
        x.bindWindow = 40_001;
        require(_accepts(x), "the mutant takes a window above T_keep");
    }

    /// Check 7 on the block hash path: 2 * 300 + 100 + 1 + 768 = 1,469 blocks
    /// to the value block, so with F_max = 30,008 a slack of 28,540 is
    /// refused and 28,539 activates.
    function test_windowBelowTheValueWaitIsRefused() public {
        _bare(ExchangeStore.MODE_NONE);
        uint256 snap = sw.snapshotState();
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_NONE);
        x.bindSlack = 28_540;
        require(_accepts(x), "terms");
        require(!_activates(), "window one block short");
        sw.revertToState(snap);
        x.bindSlack = 28_539;
        require(_accepts(x), "terms");
        require(_activates(), "window that fits");
    }

    /// Check 7 under the request-based source: 2 * 300 + 100 + D_S + T_V =
    /// 731 blocks to M, so a slack of 29,278 is refused and 29,277 activates
    /// (the block hash path refuses 29,277).
    function test_windowUnderTheRequestSourceFollowsM() public {
        _bare(ExchangeStore.MODE_VOTE_SIG);
        uint256 snap = sw.snapshotState();
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_VOTE_SIG);
        x.bindSlack = 29_277;
        require(_accepts(x), "terms");
        require(!_activates(), "block hash path refuses it");
        sw.revertToState(snap);
        vrf = _source();
        fairbind.setRandomness(address(vrf));
        snap = sw.snapshotState();
        x.bindSlack = 29_278;
        require(_accepts(x), "terms");
        require(!_activates(), "window one block short of M");
        sw.revertToState(snap);
        x.bindSlack = 29_277;
        require(_accepts(x), "terms");
        require(_activates(), "window that fits M");
    }

    function test_windowBelowTheValueWaitAcceptedIsCaught() public {
        moduleNames[REGISTRY] = "BindStartMutants.sol:AnyWindowRegistry";
        _bare(ExchangeStore.MODE_NONE);
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_NONE);
        x.bindSlack = 28_540;
        require(_accepts(x), "terms");
        require(_activates(), "the mutant activates a window one block short");
    }

    /// Activation with one F_max of terms that setExchangeTerms took.
    function _activatesWith(uint8 m, uint32 bindWindow) internal returns (bool ok) {
        uint256 snap = sw.snapshotState();
        ExchangeStore.Input memory x = _input(m);
        x.bindWindow = bindWindow;
        require(_accepts(x), "terms");
        ok = _activates();
        sw.revertToState(snap);
    }

    /// F_max in [L_F + marginBlocks - 1, T_hold - 1] (the path enumeration 4).
    /// Without batch terms L_F is the judgment delay 25,773 of the test
    /// deadlines (appealBlocks 600), so [26,272, 39,999]; a proof profile has L_F,P = O_s + T_p + 1 = (600 + 100 + 768
    /// + 200 + 200) + 300 + 1 = 2,169, so [2,668, 39,999]. F_max = T_keep =
    /// 40,000 passes check 6 and fails here.
    function test_windowOutsideTheStopRangeIsRefused() public {
        _bare(ExchangeStore.MODE_NONE);
        require(!_activatesWith(ExchangeStore.MODE_NONE, 26_271), "below L_F + margin - 1");
        require(_activatesWith(ExchangeStore.MODE_NONE, 26_272), "L_F + margin - 1");
        require(_activatesWith(ExchangeStore.MODE_NONE, 39_999), "T_hold - 1");
        require(!_activatesWith(ExchangeStore.MODE_NONE, 40_000), "T_hold");
        _bare(ExchangeStore.MODE_PROOF);
        require(!_activatesWith(ExchangeStore.MODE_PROOF, 2_667), "proof: below L_F,P + margin - 1");
        require(_activatesWith(ExchangeStore.MODE_PROOF, 2_668), "proof: L_F,P + margin - 1");
        require(!_activatesWith(ExchangeStore.MODE_PROOF, 40_000), "proof: T_hold");
    }

    function test_windowOutsideTheStopRangeAcceptedIsCaught() public {
        moduleNames[REGISTRY] = "BindStartMutants.sol:AnyRangeRegistry";
        _bare(ExchangeStore.MODE_NONE);
        require(_activatesWith(ExchangeStore.MODE_NONE, 26_271), "the mutant takes F_max below the range");
    }

    // ------------------------------------- the batched horizon ---------

    uint32 internal constant BIG_DV = 200;
    bool internal vrfFirst;
    uint32 internal bigTv = T_V;
    uint32 internal vrfDv = BIG_DV;
    uint32 internal margin = 500;
    uint32 internal keeperSlack = 10;

    function _beforeProfile() internal override {
        if (!vrfFirst) return;
        vrf = new FairBindVrf(address(fairbind), new MockVrfVerifier(), abi.encode(hv.addr(VRF_KEY)), vrfDv, bigTv);
        fairbind.setRandomness(address(vrf));
    }

    /// A profile whose beacon delay is the floor D_S = 201 (D_V = 200, T_V =
    /// 20) and whose hold is `hold`. The profile check counts the judgment
    /// delay 25,214 (opening 2,201), so any hold from 25,714 passes it.
    function _batchedProfile(uint32 hold) internal view returns (FairBindCore.ServiceProfileInput memory p) {
        p = _exchangeProfile();
        p.marginBlocks = margin;
        p.beaconDelayBlocks = BIG_DV + 1;
        p.retentionBlocks = hold;
        p.claimWindowBlocks = hold;
        p.failureWindowBlocks = hold;
        p.inconclusiveWindowBlocks = hold;
        p.enforcementBlocks = 31_000;
    }

    function setBatchExternal() external {
        BatchStore.Terms memory b;
        b.batched = true;
        b.assignDelay = BIG_DV + 1;
        b.keeperSlack = keeperSlack;
        b.slotValue = 10_000;
        b.termsHash = keccak256(
            abi.encode(
                keccak256("fairbind/batch-terms/v1"), uint32(PROFILE), b.assignDelay, b.keeperSlack, b.depositPpm,
                b.auditPpm, b.contestBlocks, b.sideGainPpm, b.slotValue, address(vrf), keccak256(vrf.publicKey()),
                uint256(vrf.responseBlocks()), uint256(vrf.deadlineSlackBlocks())
            )
        );
        IBatchedFairBind(address(fairbind)).setBatchTerms(PROFILE, b);
    }

    /// Deploys the batched vote profile with hold `hold`, with signature-free
    /// exchange terms of F_max `bindWindow` unless it is zero, and reports
    /// whether it activates.
    function _batchedActivates(uint32 hold, uint32 bindWindow) internal returns (bool) {
        mode = ExchangeStore.MODE_NONE;
        skipActivation = true;
        vrfFirst = true;
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(_batchedProfile(hold), _input(ExchangeStore.MODE_NONE), false);
        this.setBatchExternal();
        if (bindWindow != 0) {
            ExchangeStore.Input memory x = _input(ExchangeStore.MODE_NONE);
            x.bindWindow = bindWindow;
            require(_accepts(x), "terms");
        }
        return _activates();
    }

    /// L_F of the batched profile: O_s = 600 + 100 + 201 + 200 + 200 = 1,301,
    /// O^S = max(1,301 + 201, min(1,301, 1,860) + 900 + 201) = 2,402, core_0
    /// = 22,206 (test deadlines, appealBlocks 600), 2 * D_S = 402 and the
    /// review seals 403: 25,413. The hold must be at least L_F + marginBlocks
    /// = 25,913, which the profile check (25,714) does not see. Without
    /// exchange terms the hold check alone decides; with them F_max in
    /// [25,912, hold - 1] also requires it.
    function test_batchedHoldBelowItsCaseLengthIsRefused() public {
        require(!_batchedActivates(25_912, 0), "hold one block short of L_F + margin");
        require(_batchedActivates(25_913, 0), "hold L_F + margin");
        require(!_batchedActivates(25_913, 25_911), "F_max below L_F + margin - 1");
        require(_batchedActivates(25_913, 25_912), "F_max = L_F + margin - 1");
    }

    /// The keeper slack: (6m + 4) * keeperSlack = 22 * keeperSlack <=
    /// marginBlocks - 1 = 499, so 22 activates and 23 does not (T_V = 50 >=
    /// keeperSlack, and the hold
    /// 31,000 covers L_F + 500 = 25,913; L_F does not use T_V).
    function test_keeperSlackAboveTheMarginIsRefused() public {
        bigTv = 50;
        keeperSlack = 22;
        require(_batchedActivates(31_000, 0), "22 * 22 = 484");
        keeperSlack = 23;
        require(!_batchedActivates(31_000, 0), "22 * 23 = 506");
    }

    /// The keeper slack against the review seal: keeperSlack <= sealBlocks -
    /// 2 = 198. Under D_V = 10, T_V = 200 and marginBlocks 5,000 (22 * 199 +
    /// 1 <= 5,000; the hold 31,000 covers L_F + 5,000 = 29,653 and the profile
    /// check's 25,214 + 5,000), 198 activates and 199 does not.
    function test_keeperSlackAboveTheSealIsRefused() public {
        vrfDv = 10;
        bigTv = 200;
        margin = 5_000;
        keeperSlack = 198;
        require(_batchedActivates(31_000, 0), "198 = sealBlocks - 2");
        keeperSlack = 199;
        require(!_batchedActivates(31_000, 0), "199 > sealBlocks - 2");
    }

    /// The mutation build without the batched activation check takes both
    /// keeper slacks.
    function test_keeperSlackAboveTheBoundsAcceptedIsCaught() public {
        moduleNames[REGISTRY] = "BindStartMutants.sol:ShortBatchHoldRegistry";
        bigTv = 50;
        keeperSlack = 23;
        require(_batchedActivates(31_000, 0), "the mutant takes 22 * 23 > 499");
        vrfDv = 10;
        bigTv = 200;
        margin = 5_000;
        keeperSlack = 199;
        require(_batchedActivates(31_000, 0), "the mutant takes 199 > sealBlocks - 2");
    }

    function test_batchedHoldBelowItsCaseLengthAcceptedIsCaught() public {
        moduleNames[REGISTRY] = "BindStartMutants.sol:ShortBatchHoldRegistry";
        require(_batchedActivates(25_912, 0), "the mutant activates a short hold");
    }

    // ------------------------------------- 8.2 row 25: SAMPLE without anchor

    /// No account anchors epoch 0: the keeper's request is refused in A and
    /// taken in A + 1 and the value is stored by M (delivered <= M, the
    /// condition under which the contract takes it); the missed anchor ends
    /// the seller's epoch on its own.
    function test_sampleRequestOfAnEpochWithoutAnchors() public {
        _setUpVrf();
        _buy();
        hv.roll(A);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fairbind.requestSampleValue(PROFILE, 0);
        hv.roll(A + 1);
        _request(0);
        (uint64 requested,, uint64 deadline) = vrf.requestTimes(_sampleId(0));
        require(requested == A + 1 && deadline == M, "request of epoch 0 without an anchor");
        hv.roll(A + 1 + D_V);
        _fulfill(0);
        (bool ready,) = vrf.valueOf(_sampleId(0));
        (, uint64 delivered,) = vrf.requestTimes(_sampleId(0));
        require(ready && delivered <= M, "value stored by M");
        fairbind.timeoutAnchor(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.EPOCH_FAILED), "missed anchor");
    }

    /// Two accounts of the profile in epoch 0: the first misses its anchor
    /// (kind M), the second anchors. The one request (profile, A) carries no
    /// account; the second account's seal takes its value, which is the value
    /// of the first account's epoch as well, and the first account's epoch
    /// ends by timeoutAnchor whatever the value.
    function test_sampleValueOfAnEpochWithAMissedAnchor() public {
        _setUpVrf();
        uint32 first = sellerId;
        _buy();
        hv.startPrank(SELLER_OWNER);
        uint32 second = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(_exchangeProfile().sellerPenalty));
        hv.stopPrank();
        sellerId = second;
        _anchorX(0, _one(_buy()));
        hv.roll(A + 1);
        _request(0);
        hv.roll(A + 1 + D_V + 1);
        _fulfill(0);
        fairbind.timeoutAnchor(first, 0);
        require(fairbind.getAnchor(first, 0).state == uint8(FairBindCore.EpochState.EPOCH_FAILED), "missed anchor");
        hv.roll(A + 1 + D_V + 2);
        fairbind.seal(second, 0);
        (, bytes32 value) = vrf.valueOf(_sampleId(0));
        require(fairbind.getAnchor(second, 0).randomness == value, "seal takes the value of (profile, A)");
    }

    /// The mutation build that needs an anchored account refuses the request
    /// of an epoch without anchors, so no value comes by M.
    function test_sampleRequestTiedToAnAnchorIsCaught() public {
        moduleNames[RECOVERY] = "BindStartMutants.sol:AnchoredSampleRecovery";
        _setUpVrf();
        _buy();
        hv.roll(A + 1);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fairbind.requestSampleValue(PROFILE, 0);
    }

}
