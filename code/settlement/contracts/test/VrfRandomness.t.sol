// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { IVrfVerifier } from "../src/randomness/IVrfVerifier.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { MockVrfVerifier } from "./MockVrfVerifier.sol";
import { LateAcceptingVrf, BlockHashAlphaVrf, LateTakingPublication } from "./VrfMutants.sol";

/// ADR 0031 (design 2 rules D2-16, D2-20 (b), D2-23): a request-based source
/// behind IRandomness. Epoch 0 of the base profile has its anchor deadline
/// A = 700. The test source has D_V = 10 and T_V = 20, so D_S = 11, the epoch's
/// value block is A + 1 + D_S = 712 and the SAMPLE deadline is M = A + D_S + T_V
/// = 731. Responses are signed by a test key (MockVrfVerifier); a test makes a
/// response late or absent by when, or whether, it delivers it.
contract VrfRandomnessTest is ModuleSwapBase {
    uint256 internal constant G = 10_000;
    uint64 internal constant A = 700;
    uint32 internal constant D_V = 10;
    uint32 internal constant T_V = 20;
    uint64 internal constant M = A + D_V + 1 + T_V;
    uint256 internal constant VRF_KEY = 0x5EED;
    uint8 internal constant SAMPLE = 1;
    uint8 internal constant AUX = 3;
    address internal constant KEEPER = address(0x4EE9E2);
    uint8 internal constant WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);

    MockVrfVerifier internal verifier;
    FairBindVrf internal vrf;

    // ------------------------------------------------------------- helpers

    function _source(string memory adapter) internal returns (FairBindVrf) {
        bytes memory pk = abi.encode(hv.addr(VRF_KEY));
        if (keccak256(bytes(adapter)) == keccak256("late")) {
            return new LateAcceptingVrf(address(fairbind), verifier, pk, D_V, T_V);
        }
        if (keccak256(bytes(adapter)) == keccak256("blockhash")) {
            return new BlockHashAlphaVrf(address(fairbind), verifier, pk, D_V, T_V);
        }
        return new FairBindVrf(address(fairbind), verifier, pk, D_V, T_V);
    }

    /// Deploys with the given module carrying seal and VRF adapter and sets the
    /// adapter as the randomness source at block 5.
    function _setUpWith(string memory sealModule, string memory adapter, FairBindCore.ServiceProfileInput memory p)
        internal
    {
        string[10] memory names = _productionModules();
        if (bytes(sealModule).length != 0) names[PUBLICATION] = sealModule;
        _deployModules(names, p);
        verifier = new MockVrfVerifier();
        vrf = _source(adapter);
        hv.roll(5);
        fairbind.setRandomness(address(vrf));
        require(fairbind.getRandomnessKind(), "request-based source detected");
    }

    function _profile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 500_000;
        p.recheckPpm = 0;
    }

    function _sampleInput() internal pure returns (bytes memory) {
        return abi.encode(uint32(PROFILE), A);
    }

    function _sampleId() internal pure returns (bytes32) {
        return keccak256(abi.encode(SAMPLE, _sampleInput()));
    }

    function _expectedAlpha(uint8 kind, bytes memory input) internal view returns (bytes memory) {
        return abi.encode("FairBind/vrf/v1", block.chainid, address(fairbind), kind, input);
    }

    function _proofOf(bytes32 id) internal returns (bytes memory proof, bytes32 output) {
        proof = _sig(VRF_KEY, keccak256(vrf.storedAlpha(id)));
        output = keccak256(abi.encode(verifier.OUTPUT_DOMAIN(), proof));
    }

    function _fulfill(bytes32 id) internal returns (bytes32 output) {
        bytes memory proof;
        (proof, output) = _proofOf(id);
        hv.prank(KEEPER);
        vrf.fulfill(id, output, proof);
    }

    function fulfillExternal(bytes32 id) external returns (bytes32) {
        return _fulfill(id);
    }

    function sealExternal() external {
        fairbind.seal(sellerId, 0);
    }

    /// Eight purchases in epoch 0, anchored at block 600.
    function _anchored() internal returns (bytes32[] memory ns) {
        hv.roll(10);
        ns = new bytes32[](8);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
    }

    function _requestSample() internal {
        hv.roll(A + 1);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 0);
    }

    // ------------------------------------------------------ SAMPLE requests

    /// The value block follows D_S of the source, and the request rule holds:
    /// no request before A + 1, any caller after, a repeated request keeps the
    /// stored input, and none after M.
    function test_sampleRequestFollowsTheRequestRule() public {
        _setUpWith("", "", _profile());
        _anchored();
        require(fairbind.getAnchor(sellerId, 0).randomBlock == A + 1 + D_V + 1, "value block A + 1 + D_S");
        hv.roll(A);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fairbind.requestSampleValue(PROFILE, 0);
        _requestSample();
        (uint64 requested, uint64 delivered, uint64 deadline) = vrf.requestTimes(_sampleId());
        require(requested == A + 1 && delivered == 0 && deadline == M, "request record");
        require(keccak256(vrf.storedAlpha(_sampleId())) == keccak256(_expectedAlpha(SAMPLE, _sampleInput())), "alpha");
        hv.roll(A + 5);
        fairbind.requestSampleValue(PROFILE, 0);
        (requested,, deadline) = vrf.requestTimes(_sampleId());
        require(requested == A + 1 && deadline == M, "a repeated request changes nothing");
        hv.roll(M + 1);
        hv.expectRevert(FairBindCore.DeadlinePassed.selector);
        fairbind.requestSampleValue(PROFILE, 0);
    }

    /// The input is (domain, chain id, consumer, kind, input) and carries no
    /// block hash: requests in blocks with different hashes store the same
    /// alpha. A mutation build that puts the parent hash in alpha is caught.
    function _alphaWithoutBlockHash(string memory adapter) internal returns (bool) {
        _setUpWith("", adapter, _profile());
        _anchored();
        hv.roll(A + 1);
        hv.setBlockhash(A, keccak256("some parent hash"));
        fairbind.requestSampleValue(PROFILE, 0);
        return keccak256(vrf.storedAlpha(_sampleId())) == keccak256(_expectedAlpha(SAMPLE, _sampleInput()));
    }

    function test_alphaCarriesNoBlockHash() public {
        require(_alphaWithoutBlockHash(""), "alpha");
    }

    function test_alphaWithABlockHashIsCaught() public {
        require(!_alphaWithoutBlockHash("blockhash"), "mutation caught");
    }

    /// Only the consumer may request, and another consumer's alpha differs.
    function test_onlyTheConsumerRequests() public {
        _setUpWith("", "", _profile());
        hv.prank(KEEPER);
        hv.expectRevert(FairBindVrf.Unauthorized.selector);
        vrf.request(SAMPLE, _sampleInput(), M);
        FairBindVrf other = new FairBindVrf(address(0xC0FFEE), verifier, abi.encode(hv.addr(VRF_KEY)), D_V, T_V);
        require(keccak256(other.alphaOf(SAMPLE, _sampleInput())) != keccak256(vrf.alphaOf(SAMPLE, _sampleInput())),
            "bound to the consumer");
    }

    // ------------------------------------------------------- responses

    /// A response whose proof does not check against the fixed key, or whose
    /// output does not match its proof, is refused; the value is stored once.
    function test_wrongProofAndSecondResponseAreRefused() public {
        _setUpWith("", "", _profile());
        _anchored();
        _requestSample();
        bytes32 id = _sampleId();
        bytes memory wrong = _sig(VRF_KEY + 1, keccak256(vrf.storedAlpha(id)));
        bytes32 wrongOutput = keccak256(abi.encode(verifier.OUTPUT_DOMAIN(), wrong));
        hv.expectRevert(FairBindVrf.InvalidProof.selector);
        vrf.fulfill(id, wrongOutput, wrong);
        (bytes memory proof, bytes32 output) = _proofOf(id);
        hv.expectRevert(FairBindVrf.InvalidProof.selector);
        vrf.fulfill(id, keccak256("another output"), proof);
        hv.expectRevert(FairBindVrf.UnknownRequest.selector);
        vrf.fulfill(keccak256("no such request"), output, proof);
        vrf.fulfill(id, output, proof);
        hv.expectRevert(FairBindVrf.AlreadyDelivered.selector);
        vrf.fulfill(id, output, proof);
        (bool ready, bytes32 value) = vrf.valueOf(id);
        require(ready && value == output, "stored once");
    }

    /// A response after D_V but by M is taken: the epoch seals with it and
    /// its draw follows it.
    function test_lateButTimelyValueSealsTheEpoch() public {
        _setUpWith("", "", _profile());
        bytes32[] memory ns = _anchored();
        _requestSample();
        hv.roll(M);
        bytes32 output = _fulfill(_sampleId());
        hv.roll(M + 1);
        hv.prank(KEEPER);
        fairbind.seal(sellerId, 0);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.SEALED) && rec.randomness == output, "sealed with the value");
        uint256 sampled;
        for (uint256 i; i < ns.length; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            require(eligible == _sampledCopy(output, sellerId, 0, ns[i], 500_000), "draw follows the value");
            if (eligible) sampled++;
        }
        require(sampled != 0 && sampled != ns.length, "a partial sample");
    }

    /// No value before the epoch's value block, and none while unrequested.
    function test_sealWaitsForTheValue() public {
        _setUpWith("", "", _profile());
        _anchored();
        hv.roll(A + 1 + D_V + 2);
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        fairbind.requestSampleValue(PROFILE, 0);
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
    }

    /// A response after M is refused by the adapter; the epoch never seals and
    /// releases nothing. With an adapter that stores it anyway the contract
    /// still refuses it; a seal module that takes it is caught.
    function _lateValueRefused(string memory sealModule, string memory adapter) internal returns (bool) {
        _setUpWith(sealModule, adapter, _profile());
        bytes32[] memory ns = _anchored();
        _requestSample();
        hv.roll(M + 1);
        (bool stored,) = address(this).call(abi.encodeCall(this.fulfillExternal, (_sampleId())));
        if (keccak256(bytes(adapter)) != keccak256("late")) require(!stored, "adapter refuses after M");
        (bool sealOk,) = address(this).call(abi.encodeCall(this.sealExternal, ()));
        if (sealOk) return false;
        hv.roll(50_000);
        (bool released,) = address(this).call(abi.encodeCall(this.releaseExternal, (ns[0])));
        return !released && fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED);
    }

    function test_valueAfterTheDeadlineIsRefused() public {
        require(_lateValueRefused("", ""), "late value refused");
    }

    function test_contractRefusesALateValueAnAdapterStored() public {
        require(_lateValueRefused("", "late"), "late value refused by the contract");
    }

    function test_takingALateValueIsCaught() public {
        require(!_lateValueRefused("VrfMutants.sol:LateTakingPublication", "late"), "mutation caught");
    }

    /// Without a response the epoch stays anchored and nothing is released.
    function test_noResponseHoldsTheEpoch() public {
        _setUpWith("", "", _profile());
        bytes32[] memory ns = _anchored();
        _requestSample();
        hv.roll(10_000);
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        hv.roll(60_000);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(ns[0]);
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    // ------------------------------------------------------------ redraws

    /// A sampled purchase whose first search is exhausted (every verifier's
    /// room is 0.9 USDC, below the liability of 1.01 USDC), on a VRF epoch.
    function _waitingOnVrf() internal returns (bytes32 n) {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.bucketCapacity = 20;
        p.verifierExposurePpm = 100_000;
        _setUpWith("", "", p);
        hv.roll(10);
        n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        _requestSample();
        _fulfill(_sampleId());
        hv.roll(A + 1 + D_V + 2);
        fairbind.seal(sellerId, 0);
        fairbind.openSample(n);
        require(fairbind.getCase(n).state == WAITING, "waiting");
    }

    /// Tops up every verifier and writes the next checkpoint one block later.
    function _newerCheckpoint() internal returns (uint64 version) {
        for (uint32 id = 1; id <= 14; id++) fairbind.topUpVerifierBond(id, 10_000_000);
        hv.roll(_now() + 1);
        hv.prank(KEEPER);
        version = fairbind.checkpointVerifierTree(PROFILE);
    }

    function _redrawId(bytes32 n, uint32 redraw, uint64 t) internal pure returns (bytes32) {
        return keccak256(abi.encode(AUX, abi.encode(keccak256("FairBind/redraw/v1"), n, uint8(1), redraw, t)));
    }

    /// The candidate of (value, n, initial stage, attempt 0) on a checkpoint of
    /// fourteen equal weights where every verifier has room.
    function _firstCandidate(bytes32 value, bytes32 n) internal pure returns (uint32) {
        uint256 ticket = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, n, uint8(1), uint8(0), uint32(0))))
            % (14 * 20_000_000);
        return uint32(ticket / 20_000_000) + 1;
    }

    /// The redraw of a waiting case uses the AUX value of a use registered
    /// after the checkpoint it searches, asked for in a later block.
    function test_redrawUsesTheAuxValueOfItsRegisteredUse() public {
        bytes32 n = _waitingOnVrf();
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.registerRedraw(n);
        uint64 version = _newerCheckpoint();
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.NotRegistered.selector);
        fairbind.assignVerifier(n);
        hv.prank(KEEPER);
        fairbind.registerRedraw(n);
        uint64 t = uint64(_now());
        require(fairbind.getRedrawUse(n).checkpointVersion == version && fairbind.getRedrawUse(n).redraw == 1, "use");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.registerRedraw(n);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fairbind.requestRedrawValue(n);
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fairbind.requestRedrawValue(n);
        bytes32 id = _redrawId(n, 1, t);
        bytes memory input = abi.encode(keccak256("FairBind/redraw/v1"), n, uint8(1), uint32(1), t);
        require(keccak256(vrf.storedAlpha(id)) == keccak256(_expectedAlpha(AUX, input)), "AUX alpha");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.assignVerifier(n);
        hv.roll(t + 3);
        hv.prank(KEEPER);
        fairbind.requestRedrawValue(n);
        (uint64 requested,,) = vrf.requestTimes(id);
        require(requested == t + 1, "a repeated request keeps the first");
        bytes32 value = _fulfill(id);
        hv.prank(KEEPER);
        fairbind.assignVerifier(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.JUDGING) && c.randomness == value, "assigned with the AUX value");
        require(c.assignedVerifierId == _firstCandidate(value, n), "first candidate of the value");
        FairBindCore.AssignmentWait memory w = fairbind.getAssignmentWait(n);
        require(w.checkpointVersion == version && w.redraws == 1, "searched the registered checkpoint");
    }

    /// Without a response by the first request + D_V + T_V the redraw exits:
    /// the case ends without a verdict, the seller is suspended, the account
    /// freezes from the sale and opens its claim window, nothing is counted or
    /// deducted, and the buyer can claim. A later value changes nothing.
    function test_redrawWithoutAResponseExitsWithoutCount() public {
        bytes32 n = _waitingOnVrf();
        _newerCheckpoint();
        hv.prank(KEEPER);
        fairbind.registerRedraw(n);
        uint64 t = uint64(_now());
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fairbind.requestRedrawValue(n);
        uint256 balance = _bond().balance;
        hv.roll(t + 1 + D_V + T_V);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutRedrawValue(n);
        hv.roll(t + 2 + D_V + T_V);
        hv.prank(KEEPER);
        fairbind.timeoutRedrawValue(n);
        FairBindCore.BondView memory b = _bond();
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.INCONCLUSIVE), "ended without a verdict");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(b.failureCount == 0 && b.balance == balance, "not counted, nothing deducted");
        require(b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window open");
        require(fairbind.getFreezeSpans(_bondId())[0].from == fairbind.getPurchase(n).settledBlock, "from the sale");
        (uint32 waiting,,) = fairbind.getReleaseClock(_bondId());
        require(waiting == 0, "left the wait");
        require(fairbind.purchaseState(n) == uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE), "claimable");
        _fulfill(_redrawId(n, 1, t));
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.assignVerifier(n);
        _claimWith(n, _proof(n));
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDED), "claimed");
    }
}
