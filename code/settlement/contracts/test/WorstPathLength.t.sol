// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

/// Length of the worst judgment path of a detected bad sale, from its
/// settlement block to the block of its confirmed failure (final FAIL, bond
/// frozen, claim window open), for the two profiles of
/// profiles/local-evaluation-v1.json. Every actor acts at the last block the
/// contract admits; a keeper call enabled by a deadline lands in the first
/// block past it (keeper delay zero).
///
/// The path (experiments/controller/worstpath.py): purchase settled in the first
/// block of an epoch, anchor at the anchor deadline, epoch seal at the seal
/// deadline, sample opened at the end of the open window; in every judgment
/// stage every assignment requests serve at its judge deadline, the seller
/// serves at the serve deadline, the verifier escalates at the challenge
/// deadline and the seller publishes at the publication deadline. In the
/// initial stage the first two assignments deliver FAIL at the judge deadline,
/// evidence is requested at the appeal deadline and nobody discloses it, so the
/// assignment is voided by timeoutEvidence in the block after the evidence
/// deadline; the last assignment delivers FAIL at the judge deadline, evidence
/// is requested at the appeal deadline and disclosed at the evidence deadline,
/// and the seller appeals at the renewed appeal deadline. In the two review
/// stages all but the last assignment time out at the judge deadline; each
/// review seal lapses once and the reopened seal lands at its deadline; the
/// party review overturns (PASS) and the tiebreak confirms FAIL, both at the
/// judge deadline. This is the longest of the sampled paths measured here.
///
/// Two further admissible variants are measured beside it: the non-last
/// initial assignments time out at the judge deadline instead of being voided
/// at the evidence deadline (shorter), and the case is opened by a buyer
/// WRONG_DELIVERY dispute at the end of the claim window of an unsampled sale
/// instead of by sampling (not a sampled path).
///
/// The longest path of ADR 0024 (lemma C, third edition, section 4.2) opens
/// the sample case only after a buyer NON_DELIVERY dispute, filed in the last
/// block before the keeper would open the sample, ended as delivered at the
/// publication deadline; and its tiebreak cannot progress: every tiebreak
/// assignment times out, which upholds the seller-appealed initial FAIL one
/// block after the last judge deadline. With the seller's sample receipt
/// posted at its deadline, alongside the first judgment window, its length is
/// L_F = O + 3m(2 judge + 3 serve) + m(appeal + evidence) + appeal + 3(m - 1)
/// + 2(2 seal + 3) + 1, which is judgmentDelayBlocks: 30,573 blocks for the
/// data API profile and 92,081 for the inference profile.
contract WorstPathLengthTest is ReproBase {
    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint256 internal constant VERIFIER_COUNT = 40;
    uint128 internal constant VERIFIER_BOND = 100_000_000;

    enum Opening { SAMPLE, DISPUTE, DELIVERED }
    enum Timeout { JUDGE, EVIDENCE }
    enum Ending { VERDICT, STALL }

    struct Run {
        uint256 settled;
        uint256 confirmed;
        uint256 expected;
    }

    FairBindCore.DeadlineConfig internal dc;
    FairBindCore.ServiceProfileInput internal prof;
    uint256 internal settledBlock;
    bytes16 internal purchaseKey;

    // ------------------------------------------------------------ profiles

    function _common() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.predicateId = keccak256("predicate");
        p.canonId = 0x5935caa956c625c8ff2a65a874e14a464e435cc193a0742b6ace012ce81a7a3d;
        p.epochOrigin = 1000;
        p.samplePpm = 100_000;
        p.recheckPpm = 200_000;
        p.bucketCapacity = 20;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.verifierExposurePpm = 500_000;
        p.maxAssignments = 3;
        p.minVerifiers = 14;
        p.strikeLimit = 3;
        p.beaconDelayBlocks = 768;
        p.beaconSlackL1Blocks = 0;
        p.maxInconclusivePpm = 200_000;
        p.forfeitVerifierPpm = 500_000;
        p.freezeOnInitialFail = false;
        p.minJudgedCount = 30;
        p.deadlineConfigId = 1;
    }

    /// data-api-fast-v1 of profiles/local-evaluation-v1.json with the hold
    /// period, failure window and inconclusive window at the design value
    /// caseHorizon = 31,073 (ADR 0024).
    function _dataApi()
        internal
        pure
        returns (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d)
    {
        p = _common();
        p.classId = 1;
        p.predicateId = 0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f;
        p.epochBlocks = 300;
        p.effectivePpm = 40_000;
        p.enforcementBlocks = 31_073;
        p.deferBlocks = 31_073;
        p.retentionBlocks = 31_073;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 10_000;
        p.maxBadGain = 10_000;
        p.sellerPenalty = 10_000_000;
        p.minVerifierBond = 1_000_000;
        p.verifierBondCap = 100_000_000;
        p.verifierLatePenalty = 500_000;
        p.verifierWrongPenalty = 1_000_000;
        p.disputeDeposit = 5_000_000;
        p.appealDeposit = 5_000_000;
        p.marginBlocks = 500;
        p.claimWindowBlocks = 31_073;
        p.failureLimit = 16;
        p.failureWindowBlocks = 31_073;
        p.inconclusiveWindowBlocks = 31_073;
        p.parameterHash = keccak256("data-api-fast-v1, hold 31073");
        d = FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 1800);
    }

    /// open-weights-standard-v1 of profiles/local-evaluation-v1.json with the
    /// hold period and windows at its caseHorizon, 93,081 (ADR 0024).
    function _openWeights()
        internal
        pure
        returns (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d)
    {
        p = _common();
        p.classId = 2;
        p.predicateId = 0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad;
        p.epochBlocks = 1800;
        p.effectivePpm = 20_000;
        p.enforcementBlocks = 93_081;
        p.deferBlocks = 93_081;
        p.retentionBlocks = 93_081;
        p.maxPublicationCost = 20_000_000;
        p.maxReviewCost = 10_000_000;
        p.maxPurchaseValue = 100_000;
        p.maxBadGain = 100_000;
        p.sellerPenalty = 200_000_000;
        p.minVerifierBond = 50_000_000;
        p.verifierBondCap = 1_000_000_000;
        p.verifierLatePenalty = 5_000_000;
        p.verifierWrongPenalty = 10_000_000;
        p.disputeDeposit = 20_000_000;
        p.appealDeposit = 20_000_000;
        p.marginBlocks = 1000;
        p.claimWindowBlocks = 93_081;
        p.failureLimit = 27;
        p.failureWindowBlocks = 93_081;
        p.inconclusiveWindowBlocks = 93_081;
        p.parameterHash = keccak256("open-weights-standard-v1, hold 93081");
        d = FairBindCore.DeadlineConfig(100, 200, 200, 1800, 3600, 300, 3600, 1800, 1800);
    }

    /// caseHorizon of ADR 0024: L_F plus marginBlocks.
    function _caseHorizon() internal view returns (uint256) {
        return _longestPath() + prof.marginBlocks;
    }

    /// L_F = L_any of lemma C, third edition (C3-3).
    function _longestPath() internal view returns (uint256) {
        uint256 m = prof.maxAssignments;
        return _openHorizon() + 3 * m * (2 * uint256(dc.judgeBlocks) + 3 * uint256(dc.serveBlocks))
            + m * (uint256(dc.appealBlocks) + dc.evidenceBlocks) + dc.appealBlocks + 3 * (m - 1)
            + 2 * (2 * uint256(dc.sealBlocks) + 3) + 1;
    }

    function _sampledOpening() internal view returns (uint256) {
        return 2 * uint256(prof.epochBlocks) + dc.anchorBlocks + prof.beaconDelayBlocks + dc.sealBlocks + dc.openBlocks;
    }

    function _claimedOpening() internal view returns (uint256) {
        return uint256(dc.responseBlocks) + dc.claimBlocks;
    }

    /// O = max(O_s, O_d, min(O_s, O_d) + 3 serve).
    function _openHorizon() internal view returns (uint256) {
        uint256 sampled = _sampledOpening();
        uint256 claimed = _claimedOpening();
        uint256 delivered = (sampled < claimed ? sampled : claimed) + 3 * uint256(dc.serveBlocks);
        uint256 o = sampled > claimed ? sampled : claimed;
        return delivered > o ? delivered : o;
    }

    /// Closed form of the path the test drives, for a cross-check of the
    /// measured length: R is one assignment with a full serve procedure and its
    /// verdict or timeout at the refreshed judge deadline.
    function _expected(Opening opening, Timeout timeout, Ending ending) internal view returns (uint256) {
        uint256 m = prof.maxAssignments;
        uint256 r = 2 * uint256(dc.judgeBlocks) + 3 * uint256(dc.serveBlocks);
        uint256 sampled = _sampledOpening();
        uint256 claimed = _claimedOpening();
        uint256 open = opening == Opening.SAMPLE ? sampled
            : opening == Opening.DISPUTE ? claimed
            : (sampled < claimed ? sampled : claimed) + 3 * uint256(dc.serveBlocks);
        uint256 lateInitial = timeout == Timeout.JUDGE ? r + 1 : r + dc.appealBlocks + dc.evidenceBlocks + 1;
        uint256 initial = (m - 1) * lateInitial + r + 2 * uint256(dc.appealBlocks) + dc.evidenceBlocks;
        uint256 reviewSeal = 2 * uint256(dc.sealBlocks) + 3;
        uint256 review = (m - 1) * (r + 1) + r;
        // A stalled tiebreak ends one block after its last judge deadline.
        return open + initial + 2 * (reviewSeal + review) + (ending == Ending.STALL ? 1 : 0);
    }

    // ---------------------------------------------------------- deployment

    function _deployLocal(FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) internal {
        prof = p;
        dc = d;
        hv.roll(p.epochOrigin);
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(1, d);
        fairbind.createServiceProfile(PROFILE, p);
        token.mint(address(this), uint256(VERIFIER_BOND) * VERIFIER_COUNT);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= VERIFIER_COUNT; i++) {
            fairbind.registerVerifier(uint256(1) << p.classId, hv.addr(1000 + i), VERIFIER_BOND);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        fairbind.setServiceProfileActive(PROFILE, true);
        token.mint(SELLER_OWNER, uint256(p.sellerPenalty) + uint256(p.appealDeposit));
        hv.startPrank(SELLER_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        sellerId = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(p.sellerPenalty));
        hv.stopPrank();
        buyer = hv.addr(BUYER_KEY);
        token.mint(buyer, 100_000_000);
        hv.prank(buyer);
        token.approve(address(fairbind), type(uint256).max);
    }

    // ------------------------------------------------------------- helpers

    function _request() internal pure returns (FairBindCore.CanonicalRequest memory r) {
        r.method = bytes("GET");
        r.path = bytes("/v1/quote");
        r.query = bytes("symbol=ETH-USD");
        r.headerBlock = bytes("accept:application/json\n");
        r.body = "";
    }

    /// A purchase whose request hash commits a canonical request, so that the
    /// seller can publish its response on chain.
    function _publishablePurchase(uint256 value) internal returns (bytes32 n) {
        SettleArgs memory a = _settleArgs(value);
        a.req = fairbind.canonicalRequestHash(_request(), prof.canonId);
        a.nonce = fairbind.deriveNonce(sellerId, PROFILE, CLAIMS, buyer, a.key, a.req);
        a.auth = FairBindCore.TransferAuthorization(buyer, address(fairbind), value, 0, 100, a.nonce);
        a.sig = _sig(BUYER_KEY, token.receiveAuthorizationDigest(buyer, address(fairbind), value, 0, 100, a.nonce));
        _settle(a);
        purchaseKey = a.key;
        n = a.nonce;
    }

    function _case(bytes32 n) internal view returns (FairBindCore.CaseView memory) {
        return fairbind.getCase(n);
    }

    function _step(string memory label) internal view {
        _log(label, block.number - settledBlock);
    }

    /// One assignment with the longest delivery recovery: serve requested at the
    /// judge deadline, served at the serve deadline, escalated at the challenge
    /// deadline, published at the publication deadline. The judge deadline is
    /// then renewed from the publication block.
    function _serveRound(bytes32 n) internal {
        hv.roll(_case(n).judgeDue);
        fairbind.requestServe(n);
        _step("  requestServe (judge deadline)");
        hv.roll(_case(n).serveDue);
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        _step("  served (serve deadline)");
        hv.roll(_case(n).challengeUntil);
        fairbind.escalate(n);
        _step("  escalate (challenge deadline)");
        hv.roll(_case(n).publishDue);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(SELLER_OWNER);
        fairbind.publish(n, purchaseKey, _request(), bytes("response"), r, rs);
        _step("  publish (publication deadline)");
    }

    function _timeoutJudge(bytes32 n) internal {
        hv.roll(uint256(_case(n).judgeDue) + 1);
        fairbind.timeoutJudge(n);
        require(_case(n).assignedVerifierId != 0, "replacement assigned");
        _step("  timeoutJudge + reassign (judge deadline + 1)");
    }

    function _judgeAtDeadline(bytes32 n, uint8 verdict, string memory label) internal {
        hv.roll(_case(n).judgeDue);
        _judge(n, verdict);
        _step(label);
    }

    /// A review seal that lapses once and is reopened with the same randomBlock
    /// (ADR 0021, ADR 0025), then sealed at the deadline of the reopened window,
    /// which assigns the review verifier.
    function _lapsedReviewSeal(bytes32 n) internal {
        uint256 rb = _case(n).randomBlock;
        hv.roll(rb + dc.sealBlocks + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("review", n, rb)));
        fairbind.finalizeCase(n);
        require(fairbind.getReviewReseals(n) & (uint8(1) << _case(n).stage) != 0, "seal reopened");
        require(_case(n).randomBlock == rb, "randomBlock kept");
        _step("  review seal lapsed, reopened (seal deadline + 1)");
        hv.roll(fairbind.getReviewResealDue(n));
        fairbind.sealReviewRandomness(n);
        require(_case(n).assignedVerifierId != 0, "review verifier assigned");
        _step("  review seal (reopened seal deadline) + assign");
    }

    /// One review stage: all but the last assignment time out, the last one
    /// delivers `verdict` at its judge deadline, or also times out when the
    /// stage stalls.
    function _reviewStage(bytes32 n, uint8 verdict, Ending ending) internal {
        _lapsedReviewSeal(n);
        for (uint256 i; i < prof.maxAssignments; i++) {
            _serveRound(n);
            if (i + 1 < prof.maxAssignments) {
                _timeoutJudge(n);
            } else if (ending == Ending.VERDICT) {
                _judgeAtDeadline(n, verdict, "  verdict (judge deadline)");
            } else {
                hv.roll(uint256(_case(n).judgeDue) + 1);
                fairbind.timeoutJudge(n);
                _step("  last timeoutJudge: the stalled review upholds the initial FAIL (judge deadline + 1)");
            }
        }
    }

    /// A buyer NON_DELIVERY dispute filed at the latest block before the keeper
    /// would open the sample, whose serve procedure takes every window and ends
    /// as delivered by publication.
    function _deliveredDispute(bytes32 n, uint256 sealDeadline) internal {
        uint256 claimUntil = settledBlock + dc.responseBlocks + dc.claimBlocks;
        uint256 openUntil = sealDeadline + dc.openBlocks;
        hv.roll(claimUntil < openUntil ? claimUntil : openUntil);
        FairBindCore.FairBindReceipt memory none;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), none, "");
        _step("dispute NON_DELIVERY (min(claim deadline, sample open deadline))");
        hv.roll(_case(n).serveDue);
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        _step("  served (serve deadline)");
        hv.roll(_case(n).challengeUntil);
        hv.prank(buyer);
        fairbind.escalate(n);
        _step("  escalate by the buyer (challenge deadline)");
        hv.roll(_case(n).publishDue);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(SELLER_OWNER);
        fairbind.publish(n, purchaseKey, _request(), bytes("response"), r, rs);
        require(_case(n).state == uint8(FairBindCore.CaseState.DELIVERED), "dispute delivered");
        _step("  publish: DELIVERED (publication deadline)");
    }

    /// The seller posts the sample receipt with its inclusion proof at the
    /// receipt deadline, in parallel with the first judgment window.
    function _postReceiptAtDeadline(bytes32 n) internal {
        hv.roll(fairbind.getSampleReceiptDue(n));
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.submitSampleReceipt(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(n));
        require(fairbind.getSampleReceiptDue(n) == 0, "receipt recorded");
        _step("  submitSampleReceipt (receipt deadline)");
    }

    // ---------------------------------------------------------------- path

    function _runPath(Opening opening, Timeout timeout, Ending ending) internal returns (Run memory run) {
        uint256 e = prof.epochBlocks;
        // First block of epoch 1: the epoch boundary lies as late as it can.
        settledBlock = uint256(prof.epochOrigin) + e;
        hv.roll(settledBlock);
        bytes32 n = _publishablePurchase(prof.maxPurchaseValue);
        run.settled = settledBlock;
        _step("settle (epoch start)");
        require(fairbind.getPurchase(n).epoch == 1, "epoch 1");

        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        uint256 anchorDeadline = uint256(prof.epochOrigin) + 3 * e - 1 + dc.anchorBlocks;
        hv.roll(anchorDeadline);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 1, _treeEntries(), 1, keccak256("publication"));
        _step("anchor (anchor deadline)");

        uint256 beacon = anchorDeadline + 1 + prof.beaconDelayBlocks;
        uint256 sealDeadline = beacon + dc.sealBlocks;
        bytes32 randomness;
        for (uint256 i;; i++) {
            randomness = keccak256(abi.encode("beacon", i));
            if (_sampledCopy(randomness, sellerId, 1, n, prof.samplePpm) == (opening != Opening.DISPUTE)) break;
        }
        hv.roll(sealDeadline);
        hv.setBlockhash(beacon, randomness);
        fairbind.seal(sellerId, 1);
        _step("seal (seal deadline)");

        if (opening == Opening.SAMPLE) {
            hv.roll(sealDeadline + dc.openBlocks);
            fairbind.openSample(n);
            _step("openSample + assign (end of open window)");
            _postReceiptAtDeadline(n);
        } else if (opening == Opening.DELIVERED) {
            _deliveredDispute(n, sealDeadline);
            fairbind.openSample(n);
            _step("openSample on the delivered purchase + assign (same block)");
            _postReceiptAtDeadline(n);
        } else {
            uint256 claimUntil = settledBlock + dc.responseBlocks + dc.claimBlocks;
            require(claimUntil >= sealDeadline, "dispute after the seal");
            hv.roll(claimUntil);
            FairBindCore.FairBindReceipt memory r = _receipt(n);
            bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
            hv.prank(buyer);
            fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
            fairbind.assignVerifier(n);
            _step("dispute WRONG_DELIVERY + assign (claim deadline)");
        }
        require(_case(n).assignedVerifierId != 0, "initial verifier assigned");

        // Initial stage.
        _logStr("initial stage");
        for (uint256 i; i < prof.maxAssignments; i++) {
            _serveRound(n);
            if (i + 1 < prof.maxAssignments) {
                if (timeout == Timeout.JUDGE) {
                    _timeoutJudge(n);
                } else {
                    // The verdict is voided at the evidence deadline (ADR 0009).
                    _judgeAtDeadline(n, FAIL, "  verdict FAIL (judge deadline)");
                    FairBindCore.CaseView memory c = _case(n);
                    hv.roll(fairbind.getReview(n).appealUntil);
                    hv.prank(SELLER_OWNER);
                    fairbind.requestEvidence(n, c.stage, c.attempt);
                    _step("  requestEvidence (appeal deadline)");
                    hv.roll(uint256(_case(n).evidenceDue) + 1);
                    fairbind.timeoutEvidence(n, c.stage, c.attempt);
                    require(_case(n).assignedVerifierId != 0, "replacement assigned");
                    _step("  timeoutEvidence + reassign (evidence deadline + 1)");
                }
            } else {
                _judgeAtDeadline(n, FAIL, "  initial verdict FAIL (judge deadline)");
                FairBindCore.CaseView memory c = _case(n);
                hv.roll(fairbind.getReview(n).appealUntil);
                hv.prank(SELLER_OWNER);
                fairbind.requestEvidence(n, c.stage, c.attempt);
                _step("  requestEvidence (appeal deadline)");
                hv.roll(_case(n).evidenceDue);
                hv.prank(SELLER_OWNER);
                fairbind.discloseEvidence(n, c.stage, c.attempt, EVIDENCE);
                _step("  discloseEvidence (evidence deadline)");
                hv.roll(fairbind.getReview(n).appealUntil);
                hv.prank(SELLER_OWNER);
                fairbind.appeal(n);
                _step("  appeal by the seller (renewed appeal deadline)");
            }
        }

        _logStr("party review");
        _reviewStage(n, PASS, Ending.VERDICT);
        require(_case(n).state == uint8(FairBindCore.CaseState.TIEBREAK), "overturn goes to the tiebreak");
        _logStr("tiebreak");
        _reviewStage(n, FAIL, ending);

        FairBindCore.CaseView memory f = _case(n);
        require(f.state == uint8(FairBindCore.CaseState.FINAL) && f.finalVerdict == FAIL, "final FAIL");
        FairBindCore.BondView memory bond = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "bond frozen, claim window open");
        require(bond.failureCount == 1, "confirmed failure counted");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "seller suspended");
        run.confirmed = block.number;
        run.expected = _expected(opening, timeout, ending);
    }

    function _measure(
        string memory name,
        FairBindCore.ServiceProfileInput memory p,
        FairBindCore.DeadlineConfig memory d,
        uint256 horizonInFile,
        Opening opening,
        Timeout timeout,
        Ending ending
    ) internal returns (uint256 length) {
        _deployLocal(p, d);
        _logStr(name);
        _logStr(opening == Opening.SAMPLE ? "opening: sampled" : opening == Opening.DISPUTE
            ? "opening: buyer WRONG_DELIVERY dispute" : "opening: sampled after a NON_DELIVERY dispute ended as delivered");
        _logStr(timeout == Timeout.JUDGE ? "non-last assignments: judge timeout" : "non-last initial assignments: evidence timeout");
        _logStr(ending == Ending.VERDICT ? "tiebreak: FAIL verdict" : "tiebreak: every assignment times out");
        Run memory run = _runPath(opening, timeout, ending);
        length = run.confirmed - run.settled;
        uint256 horizon = _caseHorizon();
        require(horizon == horizonInFile, "caseHorizon matches the profile file");
        require(fairbind.judgmentDelayBlocks(PROFILE) == horizon - p.marginBlocks, "judgment delay is L_F");
        _log("L_actual (settlement to confirmed failure)", length);
        _log("closed form of the driven path", run.expected);
        _log("caseHorizon", horizon);
        _log("marginBlocks", p.marginBlocks);
        _log("T_hold (retentionBlocks = deferBlocks)", p.retentionBlocks);
        _logInt("T_hold - L_actual", int256(uint256(p.retentionBlocks)) - int256(length));
        _logInt("caseHorizon - marginBlocks - L_actual", int256(horizon - p.marginBlocks) - int256(length));
        require(length == run.expected, "measured length equals the closed form");
        require(length <= horizon - p.marginBlocks, "L_actual <= caseHorizon - marginBlocks");
        require(length < p.retentionBlocks, "confirmed failure before T_hold");
    }

    // ---------------------------------------------------------------- tests

    /// The longest path of ADR 0024: L_F of lemma C, third edition.
    function test_longestPath_dataApi() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _dataApi();
        uint256 l = _measure("data-api-fast-v1", p, d, 31_073, Opening.DELIVERED, Timeout.EVIDENCE, Ending.STALL);
        require(l == 30_573, "data-api L_F");
        require(l == _longestPath(), "L_F closed form");
    }

    function test_longestPath_openWeights() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _openWeights();
        uint256 l = _measure("open-weights-standard-v1", p, d, 93_081, Opening.DELIVERED, Timeout.EVIDENCE, Ending.STALL);
        require(l == 92_081, "open-weights L_F");
        require(l == _longestPath(), "L_F closed form");
    }

    /// The directive path of worstpath.py before ADR 0024.
    function test_worstPath_dataApi() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _dataApi();
        uint256 l = _measure("data-api-fast-v1", p, d, 31_073, Opening.SAMPLE, Timeout.EVIDENCE, Ending.VERDICT);
        require(l == 29_680, "data-api L_actual");
    }

    function test_worstPath_openWeights() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _openWeights();
        uint256 l = _measure("open-weights-standard-v1", p, d, 93_081, Opening.SAMPLE, Timeout.EVIDENCE, Ending.VERDICT);
        require(l == 91_180, "open-weights L_actual");
    }

    /// Shorter admissible variant: the non-last initial assignments time out at
    /// the judge deadline and spend neither their appeal nor their evidence window.
    function test_judgeTimeoutVariant_dataApi() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _dataApi();
        uint256 l = _measure("data-api-fast-v1", p, d, 31_073, Opening.SAMPLE, Timeout.JUDGE, Ending.VERDICT);
        require(l == 25_480, "data-api judge-timeout variant");
    }

    function test_judgeTimeoutVariant_openWeights() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _openWeights();
        uint256 l = _measure("open-weights-standard-v1", p, d, 93_081, Opening.SAMPLE, Timeout.JUDGE, Ending.VERDICT);
        require(l == 83_980, "open-weights judge-timeout variant");
    }

    /// The directive path opened by a buyer dispute at the end of the claim
    /// window of an unsampled sale instead of by sampling: later than the sample
    /// opening only when responseBlocks + claimBlocks exceeds the sampled opening
    /// horizon (open-weights). Not a sampled path, so not L_actual.
    function test_disputeOpenedVariant_dataApi() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _dataApi();
        uint256 l = _measure("data-api-fast-v1", p, d, 31_073, Opening.DISPUTE, Timeout.EVIDENCE, Ending.VERDICT);
        require(l == 29_672, "data-api dispute variant");
    }

    function test_disputeOpenedVariant_openWeights() public {
        (FairBindCore.ServiceProfileInput memory p, FairBindCore.DeadlineConfig memory d) = _openWeights();
        uint256 l = _measure("open-weights-standard-v1", p, d, 93_081, Opening.DISPUTE, Timeout.EVIDENCE, Ending.VERDICT);
        require(l == 91_712, "open-weights dispute variant");
    }
}
