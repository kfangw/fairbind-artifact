// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { MockVrfVerifier } from "./MockVrfVerifier.sol";
import { IBatchedFairBind } from "./BatchInterfaces.sol";

/// The admission checks of exchange terms (ADR 0037, rule D2-13 (c) 1 to 4).
contract ExchangeAdmissionTest is ExchangeBase {
    uint32 internal constant OTHER = 4;

    function setExternal(uint32 id, ExchangeStore.Input memory x) external {
        x.termsHash = fx.exchangeTermsHash(id, x);
        fx.setExchangeTerms(id, x);
    }

    function _accepts(uint32 id, ExchangeStore.Input memory x) internal returns (bool) {
        try this.setExternal(id, x) {
            return true;
        } catch {
            return false;
        }
    }

    function _fresh(uint32 id) internal {
        fairbind.createServiceProfile(id, _exchangeProfile());
    }

    /// Every rejected input fails; the default input passes.
    function _admissionHolds(string memory ex) internal returns (bool) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _deployDefault();
        uint32 id = 10;
        ExchangeStore.Input[] memory bad = new ExchangeStore.Input[](10);
        for (uint256 i; i < bad.length; i++) bad[i] = _input(ExchangeStore.MODE_PROOF);
        bad[0].keyCap = 401_199; // (1) c_key off its formula
        bad[1].keyGas = 5_000_000;
        bad[1].keyCap = 5_001_200; // (1) c_key above maxPublicationCost
        bad[1].blockGasShare = 6_000_000;
        bad[2].keyGas = 1_000_001; // (1) above the block share
        bad[2].keyCap = 1_001_201;
        bad[3].maxUpdateBytes = 200_000; // (1) a proof larger than one transaction
        bad[4].keyBlocks = 1_830; // (2) no time left to open the dispute
        bad[5].postSlack = 71; // (3) T_bundle + slack + d_conf > T_anchor
        bad[6].refWindow = 69; // delta_ref < delta_fresh + max_skew + delay
        bad[7].verifier = address(0xBEEF); // no verifier code
        bad[8].proofBlocks = 0;
        bad[9].padLength = 0;
        for (uint256 i; i < bad.length; i++) {
            _fresh(id);
            if (_accepts(id, bad[i])) return false;
            id++;
        }
        // (4) under a vote profile without receipt signatures.
        ExchangeStore.Input memory vote = _input(ExchangeStore.MODE_NONE);
        vote.pubGas = 4_930_001;
        _fresh(id);
        if (_accepts(id, vote)) return false;
        id++;
        _fresh(id);
        return _accepts(id, _input(ExchangeStore.MODE_PROOF));
    }

    function test_admissionChecks() public {
        require(_admissionHolds(""), "checks hold");
    }

    function test_admissionWithoutChecksIsCaught() public {
        require(!_admissionHolds("ExchangeMutants.sol:OpenAdmissionExchange"), "mutation caught");
    }

    function test_termsAreFixedOnceByGovernanceBeforeActivation() public {
        _deployDefault();
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_PROOF);
        // The deployed profile is active and has its terms.
        require(!_accepts(PROFILE, x), "active profile");
        _fresh(OTHER);
        x.termsHash = keccak256("wrong");
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fx.setExchangeTerms(OTHER, x);
        x.termsHash = fx.exchangeTermsHash(OTHER, x);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fx.setExchangeTerms(OTHER, x);
        fx.setExchangeTerms(OTHER, x);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fx.setExchangeTerms(OTHER, x);
        ExchangeStore.Terms memory t = fx.getExchangeTerms(OTHER);
        require(t.mode == ExchangeStore.MODE_PROOF && t.costOn && t.keyCap == 401_200, "stored");
        require(t.sourceSetHash != 0 && t.policyHash != 0, "manifest fixed");
    }

    /// A vote profile takes receipt signatures unless its input turns them
    /// off; a proof profile cannot turn them off.
    function test_voteTakesReceiptSignaturesByDefault() public {
        _deployDefault();
        ExchangeStore.Input memory v = _input(ExchangeStore.MODE_VOTE_SIG);
        require(v.mode == ExchangeStore.INPUT_VOTE && !v.receiptSigOff, "the default vote input");
        _fresh(20);
        require(_accepts(20, v), "accepted");
        require(fx.getExchangeTerms(20).mode == ExchangeStore.MODE_VOTE_SIG, "receipt signatures on");
        ExchangeStore.Input memory off = _input(ExchangeStore.MODE_VOTE_SIG);
        off.receiptSigOff = true;
        _fresh(21);
        require(_accepts(21, off), "accepted");
        require(fx.getExchangeTerms(21).mode == ExchangeStore.MODE_NONE, "off: measured costs only");
        ExchangeStore.Input memory p = _input(ExchangeStore.MODE_PROOF);
        p.receiptSigOff = true;
        _fresh(22);
        require(!_accepts(22, p), "a proof profile keeps them");
    }

    // ------------------------------------------- batch terms, either order

    FairBindVrf internal vrfSource;

    function _withVrf() internal {
        vrfSource = new FairBindVrf(address(fairbind), new MockVrfVerifier(), abi.encode(hv.addr(0x5EED)), 10, 20);
        fairbind.setRandomness(address(vrfSource));
    }

    function _batch(uint32 id, uint32 sideGainPpm) internal view returns (BatchStore.Terms memory t) {
        t.batched = true;
        t.assignDelay = 20;
        t.keeperSlack = 10;
        t.slotValue = 10_000;
        t.sideGainPpm = sideGainPpm;
        t.termsHash = keccak256(
            abi.encode(
                keccak256("fairbind/batch-terms/v1"), id, t.assignDelay, t.keeperSlack, t.depositPpm, t.auditPpm,
                t.contestBlocks, t.sideGainPpm, t.slotValue, address(vrfSource), keccak256(vrfSource.publicKey()),
                uint256(vrfSource.responseBlocks()), uint256(vrfSource.deadlineSlackBlocks())
            )
        );
    }

    function setBatchExternal(uint32 id, uint32 sideGainPpm) external {
        IBatchedFairBind(address(fairbind)).setBatchTerms(id, _batch(id, sideGainPpm));
    }

    function _batchAccepted(uint32 id, uint32 sideGainPpm) internal returns (bool) {
        try this.setBatchExternal(id, sideGainPpm) {
            return true;
        } catch {
            return false;
        }
    }

    /// Exchange terms first, batch terms second: the side-gain grade under
    /// receipt signatures and any batch terms under a proof profile revert;
    /// batch terms without the grade under receipt signatures, and the grade
    /// under signature-free vote terms, are taken.
    function _batchAfterTermsHolds(string memory admin) internal returns (bool) {
        if (bytes(admin).length != 0) batchAdminArtifact = admin;
        _deployDefault();
        _withVrf();
        _fresh(30);
        require(_accepts(30, _input(ExchangeStore.MODE_VOTE_SIG)), "receipt terms");
        bool refused = !_batchAccepted(30, 100_000);
        _fresh(31);
        require(_accepts(31, _input(ExchangeStore.MODE_PROOF)), "proof terms");
        refused = refused && !_batchAccepted(31, 0);
        _fresh(32);
        require(_accepts(32, _input(ExchangeStore.MODE_VOTE_SIG)), "receipt terms");
        require(_batchAccepted(32, 0), "batch terms without the grade");
        _fresh(33);
        require(_accepts(33, _input(ExchangeStore.MODE_NONE)), "signature-free terms");
        require(_batchAccepted(33, 100_000), "the grade without receipt signatures");
        return refused;
    }

    function test_sideGainAfterReceiptTermsIsRefused() public {
        require(_batchAfterTermsHolds(""), "refused");
    }

    function test_sideGainAfterReceiptTermsAcceptedIsCaught() public {
        require(!_batchAfterTermsHolds("ExchangeMutants.sol:SideGainAfterTermsAdmin"), "mutation caught");
    }

    /// Batch terms first, exchange terms second (the check of
    /// setExchangeTerms).
    function test_receiptTermsAfterSideGainAreRefused() public {
        _deployDefault();
        _withVrf();
        _fresh(40);
        require(_batchAccepted(40, 100_000), "the grade");
        require(!_accepts(40, _input(ExchangeStore.MODE_VOTE_SIG)), "receipt terms refused");
        require(!_accepts(40, _input(ExchangeStore.MODE_PROOF)), "proof terms refused");
        require(_accepts(40, _input(ExchangeStore.MODE_NONE)), "signature-free terms taken");
        _fresh(41);
        require(_batchAccepted(41, 0), "batch terms");
        require(!_accepts(41, _input(ExchangeStore.MODE_PROOF)), "proof terms refused");
        require(_accepts(41, _input(ExchangeStore.MODE_VOTE_SIG)), "receipt terms taken");
    }
}
