// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { Rule8Store } from "../src/modules/Rule8Store.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { Rule8Base } from "./Rule8Base.sol";
import { FairBindRule8 } from "../src/modules/FairBindRule8.sol";

/// Rule edition 8, revision 1 (rule D2-35): the seal is one per profile
/// epoch, a seller epoch anchored by A_e is sealed by it, and verifier exits
/// are held by the state of the profile epochs instead of per-seller seal
/// delays.
contract Rule8SealTest is Rule8Base {
    function _epoch0() internal returns (bytes32 a, bytes32 b) {
        a = _buy();
        b = _buy();
        _postAnchorMatch(0, _two(a, b));
    }

    function test_r8_termsAreSetOnceBeforeActivation() public {
        _deployR8();
        Rule8Store.Terms memory t = r8.getRule8Terms(PROFILE);
        require(t.on && t.unitLog2 == 1 && t.buyerWindow == 1_800, "terms stored");
        Rule8Store.Input memory x = _r8Input();
        x.termsHash = r8.rule8TermsHash(PROFILE, x);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.setTermsExternal(x);
    }

    function test_r8_profileSealSealsTheAnchoredSellerEpoch() public {
        _deployR8();
        (bytes32 a,) = _epoch0();
        // Before the profile seal the seller epoch cannot be sealed on its own.
        hv.roll(_valueBlockOf(0) + 1);
        hv.setBlockhash(_valueBlockOf(0), keccak256(abi.encode("beacon", uint24(0))));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.sealExternal(0);
        _sealProfile(0);
        (Rule8Store.ProfileEpoch memory pe, uint32 open) = r8.getProfileEpoch(PROFILE, 0);
        require(pe.state == Rule8Store.PE_SEALED && pe.version != 0 && open == 1, "profile epoch sealed, one seller epoch open");
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "no per-seller seal written");
        // The seller epoch is sealed by the profile epoch: a sample case opens
        // without a seal of its own, and the record takes the profile's value.
        fairbind.openSample(a);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.SEALED), "sealed by the profile epoch");
        require(rec.randomness == pe.randomness && rec.sortitionVersion == pe.version, "profile value and checkpoint");
        // No verifier's exit was moved by the seal (edition 7 raised every
        // checkpoint verifier's exit-eligible block to the retention end).
        for (uint32 i = 1; i <= 14; i++) {
            require(fairbind.getVerifier(i).exitEligibleBlock == 0, "no per-seller exit delay");
        }
    }

    function test_r8_sellerSealCopiesTheProfileSeal() public {
        _deployR8();
        _epoch0();
        _sealProfile(0);
        fairbind.seal(sellerId, 0);
        (Rule8Store.ProfileEpoch memory pe,) = r8.getProfileEpoch(PROFILE, 0);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.SEALED) && rec.randomness == pe.randomness, "copied");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.sealExternal(0);
    }

    function test_r8_profileSealOnceAndNotEarly() public {
        _deployR8();
        _epoch0();
        hv.roll(_valueBlockOf(0));
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        this.sealProfileExternal(0);
        _sealProfile(0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.sealProfileExternal(0);
        // The checkpoint of A_0 holds enough verifiers: no shortage.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.timeoutSealProfileExternal(0);
    }

    function test_r8_shortageIsConfirmedPerProfileEpoch() public {
        _deployR8();
        _epoch0();
        // Epoch 1 has no checkpoint at or before A_1 with fourteen verifiers
        // once one of them left: verifier 1 exits before the checkpoint.
        fairbind.requestVerifierExit(1);
        hv.roll(_anchorDeadlineOf(1) - 1);
        fairbind.finalizeVerifierExit(1);
        fairbind.checkpointVerifierTree(PROFILE);
        hv.roll(_anchorDeadlineOf(1) + 1);
        r8.timeoutSealProfile(PROFILE, 1);
        (Rule8Store.ProfileEpoch memory pe,) = r8.getProfileEpoch(PROFILE, 1);
        require(pe.state == Rule8Store.PE_FAILED, "shortage confirmed once for the profile");
    }

    function test_r8_exitHeldWhileAnEarlierProfileEpochIsOpen() public {
        _deployR8();
        // Verifier 1 asks before A_0: epoch 0 does not hold it.
        fairbind.requestVerifierExit(1);
        _epoch0();
        // Verifier 2 asks after A_0 while epoch 0 has a seller epoch the
        // cursor has not passed: its exit waits.
        hv.roll(_anchorDeadlineOf(0) + 1);
        fairbind.requestVerifierExit(2);
        hv.roll(_anchorDeadlineOf(0) + 10);
        fairbind.finalizeVerifierExit(1);
        require(fairbind.getVerifier(1).status == uint8(FairBindCore.VerifierStatus.EXITED), "1 exited");
        hv.expectRevert(FairBindCore.ExitNotReady.selector);
        this.finalizeVerifierExitExternal(2);
        // Epoch 0 cannot close while its seller epoch is open.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.closeExternal(5);
    }

    function test_r8_epochsWithoutSalesClose() public {
        _deployR8();
        hv.roll(1_000);
        r8.closeProfileEpochs(PROFILE, 10);
        // Epochs 0, 1 and 2 are over (epoch 3 runs from block 901).
        require(r8.getClosedBelow(PROFILE) == 3, "closed below 3");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.closeExternal(10);
    }
}

/// Rule edition 8, revision 2 (rule D2-36, D2-37, D2-38 (b)(d)): the anchor
/// carries the seller's signature and anyone may submit it, the submitter is
/// paid from the profile fee pool, and two signed contents of one seller
/// epoch with different (root0, count) are a confirmed failure.
contract Rule8AnchorTest is Rule8Base {
    address internal constant SUBMITTER = address(0x5B417);

    function _r8Input() internal view override returns (Rule8Store.Input memory x) {
        x = super._r8Input();
        x.cAnchor = 1_000;
    }

    function test_r8_anyoneSubmitsTheSignedAnchorAndIsPaid() public {
        _deployR8();
        r8.fundPool(PROFILE, 5_000);
        bytes32 a = _buy();
        bytes32 b = _buy();
        for (uint256 i; i < 2; i++) _postSigned(i == 0 ? a : b);
        _anchorSignedBy(0, _two(a, b), SUBMITTER);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.ANCHORED) && rec.count == 2, "anchored");
        require(rec.root == xLevels[xLevels.length - 1][0], "root of the list");
        require(token.balanceOf(SUBMITTER) == 1_000, "submitter paid c_anchor");
        (uint256 pool,,) = r8.getFeePool(PROFILE);
        require(pool == 4_000, "paid from the pool");
        // The anchor binds receipt signatures as the seller's own anchor does.
        _matchAll(_two(a, b));
        require(_bound(a) && _bound(b), "matched");
    }

    function test_r8_signedAnchorChecksSignatureRootAndCount() public {
        _deployR8();
        bytes32 a = _buy();
        bytes32 b = _buy();
        _xTree(_two(a, b));
        hv.roll(600);
        Rule8Store.AnchorContent memory c = _content(0, 2);
        FairBindMerkle.ReceiptEntry[] memory list = _xEntries();
        // Signed by another key.
        bytes memory bad = _sig(BUYER_KEY, r8.anchorDigest(c));
        hv.expectRevert(FairBindCore.InvalidSignature.selector);
        this.anchorSignedExternal(c, list, bad);
        // A root the list does not give.
        Rule8Store.AnchorContent memory wrong = _content(0, 2);
        wrong.root = keccak256("other root");
        wrong.root0 = wrong.root;
        wrong.unitsHash = keccak256(abi.encode(wrong.root, wrong.root));
        bytes memory sw = _signContent(wrong);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.anchorSignedExternal(wrong, list, sw);
        // A count that is not the settlement count.
        Rule8Store.AnchorContent memory short = _content(0, 1);
        bytes memory ss = _signContent(short);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        this.anchorSignedExternal(short, list, ss);
        // The signed content itself is taken, once.
        bytes memory sig = _signContent(c);
        this.anchorSignedExternal(c, list, sig);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.anchorSignedExternal(c, list, sig);
    }

    function test_r8_shortPoolOwesTheFeeAndPaysItInOrder() public {
        _deployR8();
        bytes32 a = _buy();
        _anchorSignedBy(0, _one(a), SUBMITTER);
        require(token.balanceOf(SUBMITTER) == 0, "not paid yet");
        (, uint256 owedCount, uint256 head) = r8.getFeePool(PROFILE);
        require(owedCount == 1 && head == 0, "owed");
        r8.fundPool(PROFILE, 1_000);
        r8.payOwedFees(PROFILE, 10);
        require(token.balanceOf(SUBMITTER) == 1_000, "paid once the pool refilled");
        (uint256 pool,, uint256 head2) = r8.getFeePool(PROFILE);
        require(pool == 0 && head2 == 1, "queue moved");
    }

    function test_r8_doubleSignedAnchorIsAConfirmedFailure() public {
        _deployR8();
        bytes32 a = _buy();
        bytes32 b = _buy();
        _xTree(_two(a, b));
        hv.roll(600);
        Rule8Store.AnchorContent memory c1 = _content(0, 2);
        Rule8Store.AnchorContent memory c2 = _content(0, 2);
        c2.root0 = keccak256("another list");
        bytes memory s1 = _signContent(c1);
        bytes memory s2 = _signContent(c2);
        // Contents that differ only in the publication hash are no equivocation.
        Rule8Store.AnchorContent memory c3 = _content(0, 2);
        c3.publicationHash = keccak256("moved publication");
        bytes memory s3 = _signContent(c3);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.equivocationExternal(c1, s1, c3, s3);
        r8.proveAnchorEquivocation(c1, s1, c2, s2);
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(_bond().freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "confirmed failure opens the claim window");
        hv.expectRevert(FairBindCore.AlreadyFinalized.selector);
        this.equivocationExternal(c1, s1, c2, s2);
    }
}

/// Rule edition 8, revision 3 (rule D2-38 (a)(c)): the first successful
/// caller of a required call is paid the fee of its kind from the profile
/// fee pool; a call that moves no state reverts and is not paid; a
/// profile-level call is paid once per epoch; an edition 7 profile pays none.
contract Rule8FeeTest is Rule8Base {
    address internal constant KEEPER = address(0x4EE9E8);

    function _r8Input() internal view override returns (Rule8Store.Input memory x) {
        x = super._r8Input();
        x.callFees[Rule8Store.FEE_SEAL] = 200;
        x.callFees[Rule8Store.FEE_OPEN] = 100;
        x.callFees[Rule8Store.FEE_CHECKPOINT] = 30;
        x.callFees[Rule8Store.FEE_CLOSE] = 20;
    }

    function openExternal(bytes32 n) external {
        fairbind.openSample(n);
    }

    function test_r8_requiredCallsArePaidFromThePool() public {
        _deployR8();
        r8.fundPool(PROFILE, 10_000);
        bytes32 a = _buy();
        bytes32 b = _buy();
        _postAnchorMatch(0, _two(a, b));
        uint256 rb = _valueBlockOf(0);
        hv.roll(rb + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("beacon", uint24(0))));
        hv.prank(KEEPER);
        r8.sealProfile(PROFILE, 0);
        require(token.balanceOf(KEEPER) == 200, "seal fee");
        hv.prank(KEEPER);
        fairbind.openSample(a);
        require(token.balanceOf(KEEPER) == 300, "open fee");
        // A call that moves nothing reverts and pays nothing.
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.openExternal(a);
        require(token.balanceOf(KEEPER) == 300, "no fee for a reverted call");
        // The checkpoint of an epoch is paid once.
        hv.prank(KEEPER);
        fairbind.checkpointVerifierTree(PROFILE);
        hv.roll(_now() + 1);
        hv.prank(KEEPER);
        fairbind.checkpointVerifierTree(PROFILE);
        require(token.balanceOf(KEEPER) == 330, "checkpoint fee once per epoch");
        (uint256 pool,,) = r8.getFeePool(PROFILE);
        require(pool == 10_000 - 330, "paid from the pool");
    }

    function test_r8_edition7ProfilePaysNoFee() public {
        r8Off = true;
        _deployR8();
        bytes32 a = _buy();
        _postAnchorMatch(0, _one(a));
        _sealX(0);
        hv.prank(KEEPER);
        fairbind.openSample(a);
        hv.prank(KEEPER);
        fairbind.checkpointVerifierTree(PROFILE);
        require(token.balanceOf(KEEPER) == 0, "no fee under edition 7");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.fundExternal(1);
    }

    function fundExternal(uint256 amount) external {
        r8.fundPool(PROFILE, amount);
    }
}

/// Rule edition 8, revision 4 (rule D2-39): release by state. A per-seller
/// cursor passes a seller epoch only when it is anchored and sealed (R1),
/// every release unit is done, each checking that every selected sale's
/// sample case ended (R2), every buyer window closed (R3), and the earlier
/// epochs were passed (R4); it then pays the epoch's batch in one transfer.
/// Purchases with an open dispute are released alone afterwards.
contract Rule8ReleaseTest is Rule8Base {
    uint256 internal constant W0 = 700 + 1 + 768 + 1_800;

    function _three() internal returns (bytes32[] memory ns) {
        ns = new bytes32[](3);
        ns[0] = _buy();
        hv.roll(20);
        ns[1] = _buy();
        hv.roll(30);
        ns[2] = _buy();
    }

    function _firstTwo(bytes32[] memory ns) internal pure returns (bytes32[] memory a) {
        a = new bytes32[](2);
        a[0] = ns[0];
        a[1] = ns[1];
    }

    function test_r8_cursorPaysTheBatchOnceUnitsAndWindowsAreDone() public {
        _deployR8Mode(0, 40_000);
        bytes32[] memory ns = _three();
        _anchorX(0, ns);
        _sealProfileWith(0, _beaconSelecting(0, ns, 0));
        // R3: an unsigned account waits for W_0 = M_0 + w_b.
        Rule8Store.UnitItem[] memory unit0 = _items(_firstTwo(ns));
        Rule8Store.UnitItem[] memory swapped = _items(_two(ns[1], ns[0]));
        hv.roll(W0);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        this.releaseUnitExternal(0, 0, unit0);
        hv.roll(W0 + 1);
        // R2: the cursor waits for every unit.
        hv.expectRevert(FairBindCore.NotSampled.selector);
        this.passExternal();
        // A list out of settlement order does not recompute the accumulator.
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.releaseUnitExternal(0, 0, swapped);
        r8.releaseUnit(sellerId, 0, 1, _items(_one(ns[2])));
        r8.releaseUnit(sellerId, 0, 0, unit0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.releaseUnitExternal(0, 0, unit0);
        uint256 before = token.balanceOf(SELLER_OWNER);
        r8.passEpoch(sellerId);
        require(token.balanceOf(SELLER_OWNER) - before == 30_000, "the batch paid in one transfer");
        require(_bond().deferredBalance == 0, "deferred balance emptied");
        (Rule8Store.SellerEpoch memory se, uint24 cursor,) = r8.getSellerEpoch(sellerId, 0);
        require(se.passed && se.paid && cursor == 1 && se.payCount == 3, "cursor passed epoch 0");
        // Edition 7's per-purchase release is closed to a rule 8 profile.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.releaseExternal(ns[0]);
        // Epoch 1 had no sales: the cursor passes it at once; epoch 2 is not over.
        r8.passEpoch(sellerId);
        hv.roll(W0 + 1);
        (, cursor,) = r8.getSellerEpoch(sellerId, 0);
        require(cursor == 2, "empty epoch passed");
        // The profile epoch 0 is closed now that its seller epoch was passed.
        r8.closeProfileEpochs(PROFILE, 3);
        require(r8.getClosedBelow(PROFILE) >= 1, "epoch 0 closed");
    }

    function test_r8_selectedSaleHoldsTheCursorUntilItsCaseEnds() public {
        _deployR8Mode(0, 40_000);
        bytes32[] memory ns = _three();
        _anchorX(0, ns);
        // Only the second purchase is selected.
        _sealProfileWith(0, _beaconSelecting(0, ns, 2));
        // A selected sale whose sample case was never opened is not at an end state.
        hv.roll(W0 + 1);
        Rule8Store.UnitItem[] memory unit0 = _items(_firstTwo(ns));
        hv.expectRevert(FairBindCore.NotSampled.selector);
        this.releaseUnitExternal(0, 0, unit0);
        fairbind.openSample(ns[1]);
        hv.expectRevert(FairBindCore.NotSampled.selector);
        this.releaseUnitExternal(0, 0, unit0);
        // The seller misses the sample receipt: a confirmed failure tied to the
        // second sale freezes it and the sale after it.
        hv.roll(uint256(fairbind.getSampleReceiptDue(ns[1])) + 1);
        fairbind.timeoutSampleReceipt(ns[1]);
        r8.releaseUnit(sellerId, 0, 0, _items(_firstTwo(ns)));
        r8.releaseUnit(sellerId, 0, 1, _items(_one(ns[2])));
        uint256 before = token.balanceOf(SELLER_OWNER);
        r8.passEpoch(sellerId);
        (Rule8Store.SellerEpoch memory se,,) = r8.getSellerEpoch(sellerId, 0);
        require(se.passed && se.itemized && !se.paid, "the freeze stops the batch");
        require(token.balanceOf(SELLER_OWNER) == before, "nothing paid in the pass");
        // The sale before the failing one is paid alone; the one after is frozen.
        r8.releaseSeparate(ns[0]);
        require(token.balanceOf(SELLER_OWNER) - before == 10_000, "earlier sale paid");
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        this.releaseSeparateExternal(ns[2]);
    }

    function test_r8_disputedPurchaseIsLeftOutAndReleasedAlone() public {
        _deployR8Mode(0, 40_000);
        bytes32[] memory ns = _three();
        // The buyer of the first purchase disputes; the seller serves.
        _disputeNonDelivery(ns[0]);
        hv.prank(SELLER_OWNER);
        fairbind.served(ns[0], keccak256("bundle"));
        _anchorX(0, ns);
        _sealProfileWith(0, _beaconSelecting(0, ns, 0));
        hv.roll(W0 + 1);
        r8.releaseUnit(sellerId, 0, 0, _items(_firstTwo(ns)));
        r8.releaseUnit(sellerId, 0, 1, _items(_one(ns[2])));
        uint256 before = token.balanceOf(SELLER_OWNER);
        r8.passEpoch(sellerId);
        require(token.balanceOf(SELLER_OWNER) - before == 20_000, "batch without the disputed purchase");
        (Rule8Store.SellerEpoch memory se,,) = r8.getSellerEpoch(sellerId, 0);
        require(se.separateCount == 1 && se.payCount == 2, "one left out");
        // Not before its dispute ends.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.releaseSeparateExternal(ns[0]);
        fairbind.finalizeServed(ns[0]);
        uint256 mid = token.balanceOf(SELLER_OWNER);
        r8.releaseSeparate(ns[0]);
        // The value, and the seller's share of the dispute deposit of a
        // delivered non-delivery dispute (ADR 0037).
        require(token.balanceOf(SELLER_OWNER) - mid >= 10_000, "released alone after its dispute");
        require(_fs(ns[0]) == uint8(FairBindCore.FinancialState.RELEASED), "released");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.releaseSeparateExternal(ns[0]);
    }
}

/// Rule edition 8, revision 5 (rule D2-40): the attempt count m and the
/// window lengths are chosen per profile; T_win(m) is checked against the
/// profile's own failure path; every profile keeps its appeals.
contract Rule8PathTest is Rule8Base {
    function _profileWith(uint32 id, uint16 m) internal {
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.maxAssignments = m;
        p.parameterHash = keccak256(abi.encode("profile", id));
        fairbind.createServiceProfile(id, p);
    }

    function _termsFor(uint32 id, uint32 win) internal view returns (Rule8Store.Input memory x) {
        x = _r8Input();
        x.winBlocks = win;
        x.heldWindow = win + 299;
        x.termsHash = r8.rule8TermsHash(id, x);
    }

    function setTermsOfExternal(uint32 id, Rule8Store.Input memory x) external {
        r8.setRule8Terms(id, x);
    }

    function test_r8_windowFollowsTheAttemptCount() public {
        _deployR8();
        // L_F(m) under the deadlines of the base: 11,367 (m = 1), 18,570
        // (m = 2) and 25,773 (m = 3); kappa_bar = marginBlocks = 500.
        _profileWith(4, 1);
        _profileWith(5, 2);
        require(r8.rule8MinWindow(4) == 11_867 && r8.rule8MinWindow(5) == 19_070, "T_win(1), T_win(2)");
        require(r8.rule8MinWindow(PROFILE) == 26_273, "T_win(3)");
        Rule8Store.Input memory x = _termsFor(4, 11_866);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        this.setTermsOfExternal(4, x);
        r8.setRule8Terms(4, _termsFor(4, 11_867));
        r8.setRule8Terms(5, _termsFor(5, 19_070));
        require(r8.getRule8Terms(4).winBlocks == 11_867 && r8.getRule8Terms(5).on, "m = 1 and m = 2 admitted");
    }

    function test_r8_zeroBuyerWindowIsRefused() public {
        _deployR8();
        _profileWith(6, 3);
        Rule8Store.Input memory x = _termsFor(6, 31_073);
        x.buyerWindow = 0;
        x.termsHash = r8.rule8TermsHash(6, x);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        this.setTermsOfExternal(6, x);
    }
}

/// Rule edition 8, revision 6 (rule D2-41): the anchor carries the buyers'
/// receipt signatures and the contract checks them in the anchor
/// transaction, storing one slot C_e = H(R_e || R^b_e); an invalid or
/// missing signature makes only its purchase no sale (refunded), without a
/// revert; a later check reads beta_n through inclusion proofs.
contract Rule8BulkTest is Rule8Base {
    address internal constant SUBMITTER = address(0x5B417);
    uint256 internal constant OTHER_KEY = 0x0DD;

    function _r8Input() internal view override returns (Rule8Store.Input memory x) {
        x = super._r8Input();
        x.bulkSig = true;
    }

    function test_r8_bulkCheckBindsInTheAnchorTransaction() public {
        _deployR8();
        bytes32 a = _buy();
        bytes32 b = _buy();
        bytes32 c = _buy();
        keyOf[a] = BUYER_KEY;
        keyOf[b] = OTHER_KEY;
        keyOf[c] = 0;
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = a;
        ns[1] = b;
        ns[2] = c;
        bool[] memory bound = new bool[](3);
        bound[0] = true;
        BulkAnchor memory x = _bulkAnchor(0, ns, bound);
        bytes memory sig = _sig(SELLER_KEY, r8.anchorDigest(x.content));
        hv.roll(600);
        hv.prank(SUBMITTER);
        r8.anchorBulk(x.content, x.entries, sig);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.ANCHORED) && rec.root == xLevels[xLevels.length - 1][0], "anchor root over (nonce, leaf)");
        (Rule8Store.SellerEpoch memory se,,) = r8.getSellerEpoch(sellerId, 0);
        require(se.bindRoot == keccak256(abi.encode(x.content.root, x.rB)), "one slot C_e");
        // b (another key) and c (no signature) are no sales and are refunded.
        require(_fs(b) == uint8(FairBindCore.FinancialState.REFUNDABLE) && _fs(c) == uint8(FairBindCore.FinancialState.REFUNDABLE), "unbound refunded");
        require(_fs(a) == uint8(FairBindCore.FinancialState.DEFERRED) && !_bound(a), "a bound, not yet shown");
        // beta_b = 0: a proof of beta = 1 for b does not hold.
        Rule8Store.BulkEntry memory eb = _bulkEntry(b);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.proveBindingExternal(b, eb, x.content.root, x.rB);
        _proveBinding(a, x);
        require(_bound(a), "a shown bound");
        _sealProfile(0);
        fairbind.openSample(a);
        require(_state(a) != 0, "the sample case of a opens");
    }

    function test_r8_bulkAnchorNeedsTheSignedRoots() public {
        _deployR8();
        bytes32 a = _buy();
        keyOf[a] = BUYER_KEY;
        bool[] memory bound = new bool[](1);
        bound[0] = true;
        BulkAnchor memory x = _bulkAnchor(0, _one(a), bound);
        // A content whose R_e does not match the carried signatures.
        Rule8Store.AnchorContent memory wrong = x.content;
        wrong.root = keccak256("other");
        wrong.unitsHash = keccak256(abi.encode(wrong.root, wrong.root0));
        bytes memory sw = _sig(SELLER_KEY, r8.anchorDigest(wrong));
        hv.roll(600);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.anchorBulkExternal(wrong, x.entries, sw);
    }

    function anchorBulkExternal(Rule8Store.AnchorContent memory c, Rule8Store.BulkEntry[] memory es, bytes memory sig) external {
        r8.anchorBulk(c, es, sig);
    }
}

/// Rule edition 8, revision 7 (rule D2-42, D2-13 (1)): the held settlement
/// cap N_h = ceil(q_S + r_S * H_N), H_N >= (T_epoch - 1) + T_win(m); a
/// settlement at n_h >= N_h reverts, and a purchase leaves n_h when it is
/// paid by the cursor or refunded.
contract Rule8HeldTest is Rule8Base {
    uint256 internal constant W0 = 700 + 1 + 768 + 1_800;

    function _r8Input() internal view override returns (Rule8Store.Input memory x) {
        x = super._r8Input();
        // The admission minimum: (300 - 1) + 31,073.
        x.heldWindow = 31_372;
    }

    /// q_S = 2 settlements, r_S = 100 ppm per block (one settlement per
    /// 10,000 blocks): N_h = ceil(2 + 0.0001 * 31,372) = 6.
    function _slowProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _exchangeProfile();
        p.samplePpm = 40_000;
        p.effectivePpm = 40_000;
        p.bucketCapacity = 2;
        p.refillPpmPerBlock = 100;
    }

    function test_r8_heldWindowBelowTheMinimumIsRefused() public {
        skipActivation = true;
        _deployR8();
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.parameterHash = keccak256("profile 7");
        fairbind.createServiceProfile(7, p);
        Rule8Store.Input memory x = _r8Input();
        x.heldWindow = 31_371;
        x.termsHash = r8.rule8TermsHash(7, x);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        this.setTermsOf(7, x);
        x.heldWindow = 31_372;
        x.termsHash = r8.rule8TermsHash(7, x);
        r8.setRule8Terms(7, x);
    }

    function setTermsOf(uint32 id, Rule8Store.Input memory x) external {
        r8.setRule8Terms(id, x);
    }

    function test_r8_settlementStopsAtTheHeldCapAndPaidPurchasesLeaveIt() public {
        _deployR8Profile(0, _slowProfile());
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = _buy();
        ns[1] = _buy();
        (uint32 held,) = r8.getHeld(sellerId);
        require(held == 2, "two held");
        _anchorX(0, ns);
        _sealProfileWith(0, _beaconSelecting(0, ns, 0));
        hv.roll(W0 + 1);
        r8.releaseUnit(sellerId, 0, 0, _items(ns));
        r8.passEpoch(sellerId);
        (held,) = r8.getHeld(sellerId);
        require(held == 0, "paid purchases left n_h");
        // Six more fit (one per 10,000 blocks of refill); the seventh is
        // refused by N_h = 6 although the bucket holds a settlement.
        for (uint256 i = 1; i <= 6; i++) {
            hv.roll(10 + 10_000 * i);
            _buy();
        }
        (held,) = r8.getHeld(sellerId);
        require(held == 6, "six held");
        hv.roll(10 + 10_000 * 7);
        hv.expectRevert(FairBindCore.HeldSettlementCap.selector);
        this.buyExternal();
    }

    function test_r8_refundLeavesTheHeldCount() public {
        _deployR8Profile(0, _slowProfile());
        bytes32 a = _buy();
        // The buyer's non-delivery dispute ends with the refund and a
        // confirmed failure: the episode ends and its count starts from zero.
        _disputeNonDelivery(a);
        hv.roll(uint256(fairbind.getCase(a).serveDue) + 1);
        fairbind.timeoutServe(a);
        (uint32 held, uint64 floor_) = r8.getHeld(sellerId);
        require(held == 0 && floor_ != 0, "episode ended");
    }
}

/// Rule edition 8, revision 1 (rule D2-35 (d) 1 (ii)): a WRONG_DELIVERY
/// dispute holds its profile epoch open, so verifier exits that the epoch
/// holds wait for its end, even after the cursor passed the seller epoch.
contract Rule8OtherCaseTest is Rule8Base {
    uint256 internal constant W0 = 700 + 1 + 768 + 1_800;

    function noteExternal(bytes32 n) external {
        r8.noteCaseEnded(n);
    }

    function test_r8_wrongDeliveryDisputeHoldsTheProfileEpoch() public {
        _deployR8Mode(0, 40_000);
        bytes32 a = _buy();
        bytes32[] memory ns = _one(a);
        _anchorX(0, ns);
        _sealProfileWith(0, _beaconSelecting(0, ns, 0));
        FairBindCore.FairBindReceipt memory r = _receipt(a);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(a, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        require(r8.getOpenOtherCases(PROFILE, 0) == 1, "counted");
        hv.roll(W0 + 1);
        r8.releaseUnit(sellerId, 0, 0, _items(ns));
        r8.passEpoch(sellerId);
        // The seller epoch is passed, but the dispute still holds epoch 0.
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.closeExternal(5);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.noteExternal(a);
    }
}

/// Rule edition 8, revision 4 (rule D2-39 (difference)): fuzzed inclusion. Every
/// purchase is settled in a block of its own; the first selected sale i0
/// either fails its sample case (the receipt deadline passes) or keeps it
/// open. Whatever units, cursor passes and separate releases anyone calls,
/// the seller is never paid a purchase settled at or after i0.
contract Rule8InclusionFuzzTest is Rule8Base {
    uint256 internal constant W0 = 700 + 1 + 768 + 1_800;

    /// forge-config: default.fuzz.runs = 64
    function testFuzz_r8_noPaymentFromTheFirstSelectedSaleOn(uint256 seed) public {
        _deployR8Mode(0, 500_000);
        uint256 n = 3 + seed % 5;
        bytes32[] memory ns = new bytes32[](n);
        for (uint256 i; i < n; i++) {
            hv.roll(10 + i);
            ns[i] = _buy();
        }
        _anchorX(0, ns);
        // A beacon from the seed under which at least one purchase is selected.
        bytes32 beacon;
        uint256 first = type(uint256).max;
        {
            uint256 ppm = 500_000;
            uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
            for (uint256 salt;; salt++) {
                beacon = keccak256(abi.encode(seed, salt));
                for (uint256 i; i < n && first == type(uint256).max; i++) {
                    uint256 v = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), beacon, sellerId, uint24(0), ns[i])));
                    if (v < threshold) first = i;
                }
                if (first != type(uint256).max) break;
            }
        }
        _sealProfileWith(0, beacon);
        bool fails = (seed >> 8) & 1 == 1;
        fairbind.openSample(ns[first]);
        if (fails) {
            hv.roll(uint256(fairbind.getSampleReceiptDue(ns[first])) + 1);
            fairbind.timeoutSampleReceipt(ns[first]);
        }
        hv.roll(W0 + 1 + (seed >> 16) % 500);
        uint256 before = token.balanceOf(SELLER_OWNER);
        // Units of two, in an order from the seed, then the cursor and every
        // separate release; calls that revert leave nothing.
        uint256 units = (n + 1) / 2;
        for (uint256 k; k < units; k++) {
            uint256 u = (k + seed) % units;
            uint256 len = n - 2 * u < 2 ? n - 2 * u : 2;
            bytes32[] memory part = new bytes32[](len);
            for (uint256 i; i < len; i++) part[i] = ns[2 * u + i];
            Rule8Store.UnitItem[] memory items = _items(part);
            try r8.releaseUnit(sellerId, 0, uint32(u), items) { } catch { }
        }
        try r8.passEpoch(sellerId) { } catch { }
        for (uint256 i; i < n; i++) {
            try r8.releaseSeparate(ns[i]) { } catch { }
        }
        uint256 paid = token.balanceOf(SELLER_OWNER) - before;
        require(paid <= 10_000 * first, "nothing settled at or after the first selected sale is paid");
        if (!fails) require(paid == 0, "an open sample case holds the whole epoch");
    }
}
