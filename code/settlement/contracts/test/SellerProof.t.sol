// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";
import { EarlyProof, SharedPoolProof } from "./BatchMutants.sol";

/// ADR 0034: seller proofs on frozen entries, their audit, contest and
/// judgment, and the compensation pool. Every purchase is sampled; the
/// detection floor p0 is 0.4. A non-delivery failure of the first purchase d
/// freezes the account from its sale, so the later purchases j and k are
/// frozen; their sample cases pass before a proof.
contract SellerProofTest is BatchBase {
    address internal constant CONTESTER = address(0xC0C0);
    bytes internal constant ENVELOPE = bytes("evidence envelope");
    bytes32 internal d;
    bytes32 internal j;
    bytes32 internal k;
    bytes32[] internal epoch0;

    function _proofTerms(uint32 audit, uint32 contest) internal pure returns (BatchStore.Terms memory t) {
        t = _defaultTerms();
        t.auditPpm = audit;
        t.contestBlocks = contest;
    }

    function _proofProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _batchProfile();
        p.effectivePpm = 400_000;
    }

    /// The initial PASS of the sample case n, made final after its appeal
    /// window (no automatic recheck).
    function _pass(bytes32 n) internal {
        _judgeBatched(n, uint8(FairBindCore.Verdict.PASS));
    }

    function _final(bytes32 n) internal {
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        hv.roll(uint256(fairbind.getReview(n).appealUntil) + 1);
        if (_now() <= c.randomBlock) hv.roll(uint256(c.randomBlock) + 1);
        hv.setBlockhash(c.randomBlock, keccak256(abi.encode("gate", n)));
        fairbind.finalizeCase(n);
        require(_state(n) == uint8(FairBindCore.CaseState.FINAL), "final");
    }

    /// d fails (non-delivery, UNSERVED at 372), j and k are frozen; epoch 0
    /// is sealed and the sample cases of j and k pass in batch 0.
    function _frozenPair(BatchStore.Terms memory t, string memory proofModule) internal {
        proofArtifact = proofModule;
        _deployBatched(_proofProfile(), t, _equalBonds());
        hv.roll(10);
        d = _purchase(G);
        j = _purchase(G);
        k = _purchase(G);
        _unserved(d);
        delete epoch0;
        epoch0.push(d);
        epoch0.push(j);
        epoch0.push(k);
        _anchorOf(0, sellerId, SELLER_OWNER, epoch0);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(j);
        _openSample(k);
        _assignBatch(0);
        _pass(j);
        _pass(k);
        _final(j);
        _final(k);
        token.mint(CONTESTER, 1_000_000_000_000);
        hv.prank(CONTESTER);
        token.approve(address(fairbind), type(uint256).max);
    }

    function _submit(bytes32 n) internal {
        _buildTree(epoch0);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory pf = _proof(n);
        hv.prank(SELLER_OWNER);
        fb.submitProof(n, r, sig, pf, ENVELOPE);
    }

    function submitExternal(bytes32 n) external {
        _submit(n);
    }

    function _submitOk(bytes32 n) internal returns (bool ok) {
        (ok,) = address(this).call(abi.encodeCall(this.submitExternal, (n)));
    }

    /// Requests and delivers the audit value of an open proof and draws it.
    function _draw(bytes32 n) internal {
        uint64 t = fb.getProof(n).auditBlock;
        if (_now() <= t) hv.roll(uint256(t) + 1);
        hv.prank(KEEPER);
        fb.requestAuditValue(n);
        _fulfill(_auditId(n, t));
        hv.prank(KEEPER);
        fb.drawAudit(n);
    }

    /// The batch the proof case of n joined: its checkpoint and its assignment.
    function _assignProofBatch(bytes32 n) internal {
        uint24 e = fb.getBatchEntry(fb.proofCaseId(n)).batch;
        if (_now() <= _a(e)) hv.roll(uint256(_a(e)) + 1);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, e);
        _assignBatch(e);
    }

    function _judgeProof(bytes32 n, uint8 verdict) internal {
        uint32 u = fb.getProof(n).verifier;
        require(u != 0 && fb.getProof(n).state == BatchStore.P_JUDGING, "proof judging");
        fb.judgeProof(n, verdict, _sig(1000 + u, fb.proofVerdictDigest(n, verdict)));
    }

    // ------------------------------------------------------------- audit

    /// An audited proof that passes: the bond (1.5 v at p_a = 1) comes back,
    /// the entry cannot be claimed, and it is paid to the seller once its
    /// effective age reaches the hold period.
    function test_auditedProofPassesAndTheEntryIsReleased() public {
        _frozenPair(_proofTerms(1_000_000, 0), proofArtifact);
        require(fb.proofBondOf(j) == 15_000, "B_p = ceil(v (1 - x1) / x1), x1 = 0.4");
        uint256 seller0 = token.balanceOf(SELLER_OWNER);
        _submit(j);
        require(seller0 - token.balanceOf(SELLER_OWNER) == 15_000, "bond locked apart from the account");
        BatchStore.Proof memory pr = fb.getProof(j);
        require(pr.state == BatchStore.P_OPEN && pr.auditBlock == _now(), "open, audit use registered now");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fb.requestAuditValue(j);
        _draw(j);
        require(fb.getProof(j).audited && fb.getProof(j).state == BatchStore.P_BATCHED, "audited, waits for its batch");
        _buildTree(epoch0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.claimExternal(j, _proof(j));
        _assignProofBatch(j);
        _judgeProof(j, uint8(FairBindCore.Verdict.PASS));
        require(fb.getProof(j).state == BatchStore.P_CONFIRMED, "confirmed");
        require(token.balanceOf(SELLER_OWNER) == seller0, "bond back");
        require(fb.getPool(_bondOfSeller(sellerId)).weight == G, "a share of the pool");
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.releaseProven(j);
        hv.roll(45_000);
        fb.releaseProven(j);
        require(token.balanceOf(SELLER_OWNER) == seller0 + G, "paid to the seller");
    }

    /// An audited proof that fails: the bond goes to the account's pool, one
    /// failure is counted without a new freeze or deduction, the entry
    /// returns to the claim window from the verdict and its buyer claims it,
    /// and the entry takes no second proof. The pool is distributed over the
    /// proven entry k, in proportion to value.
    function test_auditedProofFailsAndItsBondCompensatesTheProvenEntry() public {
        _frozenPair(_proofTerms(1_000_000, 0), proofArtifact);
        uint32 bondId = _bondOfSeller(sellerId);
        FairBindCore.BondView memory b0 = fairbind.getBond(bondId);
        FairBindCore.FreezeSpan[] memory spans0 = fairbind.getFreezeSpans(bondId);
        _submit(j);
        _submit(k);
        _draw(j);
        _draw(k);
        _assignProofBatch(j);
        uint256 locked0 = fairbind.getLockedForfeit();
        _judgeProof(j, uint8(FairBindCore.Verdict.FAIL));
        FairBindCore.BondView memory b1 = fairbind.getBond(bondId);
        require(b1.failureCount == b0.failureCount + 1 && b1.balance == b0.balance, "counted, not deducted");
        require(fairbind.getFreezeSpans(bondId).length == spans0.length, "no new freeze");
        require(fairbind.getLockedForfeit() == locked0, "the bond is not locked");
        require(fb.getPool(bondId).balance == 15_000, "the bond is in the pool");
        require(b1.claimUntilBlock >= _now() + 40_000, "claim period from the verdict");
        require(fb.getProof(j).state == BatchStore.P_FAILED, "failed");
        require(!_submitOk(j), "one proof per entry");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.distributeCompensation(bondId);
        _judgeProof(k, uint8(FairBindCore.Verdict.PASS));
        _buildTree(epoch0);
        uint256 buyer0 = token.balanceOf(buyer);
        this.claimExternal(j, _proof(j));
        require(token.balanceOf(buyer) - buyer0 == G, "the buyer of j is refunded");
        hv.prank(KEEPER);
        fb.distributeCompensation(bondId);
        buyer0 = token.balanceOf(buyer);
        fb.claimCompensation(k);
        require(token.balanceOf(buyer) - buyer0 == 15_000, "the proven entry's buyer gets the pool");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.claimCompensation(k);
    }

    // ------------------------------------------------------------ contest

    /// p_a = 0.1%: the proof is not audited and is open to contest for 100
    /// blocks. A contest with a deposit of v that wins pays the contester its
    /// deposit and min(B_p, v); the rest of the bond goes to the pool.
    function test_contestThatWinsPaysTheContester() public {
        _frozenPair(_proofTerms(1_000, 100), proofArtifact);
        uint256 bond = fb.proofBondOf(j);
        require(bond == 24_990_000, "B_p at x1 = 0.0004");
        _submit(j);
        _draw(j);
        BatchStore.Proof memory pr = fb.getProof(j);
        require(!pr.audited && pr.state == BatchStore.P_CONTEST && pr.contestUntil == _now() + 100, "contest window");
        uint256 c0 = token.balanceOf(CONTESTER);
        hv.prank(CONTESTER);
        fb.contestProof(j);
        require(c0 - token.balanceOf(CONTESTER) == G, "deposit v");
        _assignProofBatch(j);
        _judgeProof(j, uint8(FairBindCore.Verdict.FAIL));
        require(token.balanceOf(CONTESTER) - c0 == G, "deposit back and min(B_p, v)");
        require(fb.getPool(_bondOfSeller(sellerId)).balance == bond - G, "the rest in the pool");
    }

    /// A contest that loses locks the deposit; an uncontested proof is
    /// confirmed only after its window.
    function test_lostContestLocksAndUncontestedProofWaitsForItsWindow() public {
        _frozenPair(_proofTerms(1_000, 100), proofArtifact);
        _submit(j);
        _submit(k);
        _draw(j);
        _draw(k);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.confirmProof(k);
        hv.prank(CONTESTER);
        fb.contestProof(j);
        uint64 until = fb.getProof(k).contestUntil;
        hv.roll(uint256(until) + 1);
        hv.prank(CONTESTER);
        hv.expectRevert(FairBindCore.DeadlinePassed.selector);
        fb.contestProof(k);
        uint256 seller0 = token.balanceOf(SELLER_OWNER);
        hv.prank(KEEPER);
        fb.confirmProof(k);
        require(fb.getProof(k).state == BatchStore.P_CONFIRMED, "confirmed after the window");
        require(token.balanceOf(SELLER_OWNER) - seller0 == fb.proofBondOf(k), "bond back");
        _assignProofBatch(j);
        uint256 locked0 = fairbind.getLockedForfeit();
        _judgeProof(j, uint8(FairBindCore.Verdict.PASS));
        require(fairbind.getLockedForfeit() - locked0 == G, "lost contest deposit locked");
    }

    // ---------------------------------------------- order and conditions

    /// While the sample case of k is open the proof of j is only reserved:
    /// it does not open, and it opens once k's case ends. A build that opens
    /// proofs while a sample case of the account is open is caught.
    function _proofWaitsForOpenCases(string memory proofModule) internal returns (bool) {
        proofArtifact = proofModule;
        _deployBatched(_proofProfile(), _proofTerms(1_000_000, 0), _equalBonds());
        hv.roll(10);
        d = _purchase(G);
        j = _purchase(G);
        k = _purchase(G);
        _unserved(d);
        delete epoch0;
        epoch0.push(d);
        epoch0.push(j);
        epoch0.push(k);
        _anchorOf(0, sellerId, SELLER_OWNER, epoch0);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(j);
        _openSample(k);
        _assignBatch(0);
        _pass(j);
        _pass(k);
        _final(j);
        _submit(j);
        if (fb.getProof(j).state != BatchStore.P_RESERVED) return false;
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.activateProof(j);
        _final(k);
        hv.prank(KEEPER);
        fb.activateProof(j);
        BatchStore.Proof memory pr = fb.getProof(j);
        return pr.state == BatchStore.P_OPEN && pr.auditBlock == _now();
    }

    function test_proofWaitsForTheAccountsOpenSampleCases() public {
        require(_proofWaitsForOpenCases(proofArtifact), "reserved, then opened");
    }

    function test_proofOpeningEarlyIsCaught() public {
        require(!_proofWaitsForOpenCases("BatchMutants.sol:EarlyProof"), "mutation caught");
    }

    /// The conditions on the entry and the seller: owner only, inside the
    /// frozen window, not claimed, proofs on (and back on only for later
    /// sales); a held entry cannot be claimed and the window cannot be
    /// forfeited while a proof is undecided.
    function test_proofConditions() public {
        _frozenPair(_proofTerms(1_000_000, 0), proofArtifact);
        uint32 bondId = _bondOfSeller(sellerId);
        _buildTree(epoch0);
        FairBindCore.FairBindReceipt memory r = _receipt(j);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory pf = _proof(j);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fb.submitProof(j, r, sig, pf, ENVELOPE);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.EvidenceTooLarge.selector);
        fb.submitProof(j, r, sig, pf, "");
        hv.prank(SELLER_OWNER);
        fb.setProofsOff(bondId, true);
        require(!_submitOk(j), "proofs off");
        hv.prank(SELLER_OWNER);
        fb.setProofsOff(bondId, false);
        require(!_submitOk(j), "back on only for sales after this block");
        // A claimed entry takes no proof.
        this.claimExternal(k, _proof(k));
        require(fb.getProofAccount(bondId).pending == 0, "nothing pending");
    }

    function test_heldEntryAndPendingProofKeepTheWindow() public {
        _frozenPair(_proofTerms(1_000, 100), proofArtifact);
        uint32 bondId = _bondOfSeller(sellerId);
        this.claimExternal(k, _proofFor(k));
        require(!_submitOk(k), "a claimed entry takes no proof");
        _submit(j);
        FairBindCore.ReceiptProof memory pj = _proofFor(j);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        this.claimExternal(j, pj);
        hv.roll(uint256(fairbind.getBond(bondId).claimUntilBlock) + 1);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.forfeitUnclaimed(bondId);
    }

    function _proofFor(bytes32 n) internal returns (FairBindCore.ReceiptProof memory) {
        _buildTree(epoch0);
        return _proof(n);
    }

    /// A reservation whose epoch passes its sampling deadline without a value
    /// is void: its bond comes back and the entry returns to the claim window.
    function test_reservationOfAnEpochWithoutAValueIsVoided() public {
        _deployBatched(_proofProfile(), _proofTerms(1_000_000, 0), _equalBonds());
        hv.roll(10);
        d = _purchase(G);
        hv.roll(310);
        j = _purchase(G);
        hv.roll(320);
        _unserved(d);
        delete epoch0;
        epoch0.push(d);
        _anchorOf(0, sellerId, SELLER_OWNER, epoch0);
        _sealOf(0, _sellers1());
        bytes32[] memory e1 = new bytes32[](1);
        e1[0] = j;
        _anchorOf(1, sellerId, SELLER_OWNER, e1);
        hv.roll(1001);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 1);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 1);
        hv.roll(1020);
        _buildTree(e1);
        FairBindCore.FairBindReceipt memory r = _receipt(j);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory pf = _proof(j);
        uint256 seller0 = token.balanceOf(SELLER_OWNER);
        hv.prank(SELLER_OWNER);
        fb.submitProof(j, r, sig, pf, ENVELOPE);
        require(fb.getProof(j).state == BatchStore.P_RESERVED, "reserved");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.voidReservation(j);
        hv.roll(1032);
        hv.prank(KEEPER);
        fb.voidReservation(j);
        require(fb.getProof(j).state == 0 && token.balanceOf(SELLER_OWNER) == seller0, "void, bond back");
        require(fairbind.getPurchase(j).financialState == uint8(FairBindCore.FinancialState.DEFERRED), "claimable");
        require(fb.getProofAccount(_bondOfSeller(sellerId)).pending == 0, "nothing pending");
    }

    /// An unanswered audit value ends the proof without a verdict; it counts
    /// as the entry's one proof.
    function test_unansweredAuditValueEndsTheProof() public {
        _frozenPair(_proofTerms(1_000_000, 0), proofArtifact);
        _submit(j);
        uint64 t = fb.getProof(j).auditBlock;
        hv.roll(uint256(t) + 1);
        hv.prank(KEEPER);
        fb.requestAuditValue(j);
        hv.roll(uint256(t) + 1 + 30);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.timeoutAuditValue(j);
        hv.roll(uint256(t) + 1 + 31);
        hv.prank(KEEPER);
        fb.timeoutAuditValue(j);
        require(fb.getProof(j).state == BatchStore.P_ENDED, "ended");
        require(!_submitOk(j), "counts as the entry's proof");
        this.claimExternal(j, _proofFor(j));
    }

    /// A confirmed proof is void when its purchase later has a confirmed
    /// failure (here an equivocation): the entry leaves the pool's shares.
    function test_laterFailureVoidsAConfirmedProof() public {
        _frozenPair(_proofTerms(1_000_000, 0), proofArtifact);
        _submit(j);
        _draw(j);
        _assignProofBatch(j);
        _judgeProof(j, uint8(FairBindCore.Verdict.PASS));
        uint32 bondId = _bondOfSeller(sellerId);
        require(fb.getPool(bondId).weight == G, "weighted");
        FairBindCore.FairBindReceipt memory a = _receipt(j);
        FairBindCore.FairBindReceipt memory b = _receipt(j);
        b.responseHash = keccak256("another response");
        fairbind.proveEquivocation(a, _sig(SELLER_KEY, fairbind.receiptDigest(a)), b, _sig(SELLER_KEY, fairbind.receiptDigest(b)));
        require(fb.getProof(j).state == BatchStore.P_INVALID && fb.getPool(bondId).weight == 0, "void");
    }

    // ------------------------------------------------- pool per account

    /// Seller B's failed proof funds only B's pool: A's proven entry gets
    /// nothing from it. A build with one shared pool pays A's buyer from B's
    /// forfeited bond.
    function _poolStaysWithItsAccount(string memory proofModule) internal returns (bool) {
        proofArtifact = proofModule;
        _deployBatched(_proofProfile(), _proofTerms(1_000_000, 0), _equalBonds());
        _addSellerB();
        hv.roll(10);
        d = _purchase(G);
        j = _purchase(G);
        bytes32 dB = _purchaseOf(sellerB, G);
        bytes32 jB = _purchaseOf(sellerB, G);
        _unserved(d);
        _unserved(dB);
        delete epoch0;
        epoch0.push(d);
        epoch0.push(j);
        bytes32[] memory eB = new bytes32[](2);
        eB[0] = dB;
        eB[1] = jB;
        _anchorOf(0, sellerB, SELLER_B_OWNER, eB);
        _anchorOf(0, sellerId, SELLER_OWNER, epoch0);
        _sealOf(0, _sellers2());
        hv.roll(800);
        _openSample(j);
        _openSample(jB);
        _assignBatch(0);
        _pass(j);
        _pass(jB);
        _final(j);
        _final(jB);
        _submit(j);
        _buildTree(eB);
        FairBindCore.FairBindReceipt memory r = _receipt(jB);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory pf = _proof(jB);
        hv.prank(SELLER_B_OWNER);
        fb.submitProof(jB, r, sig, pf, ENVELOPE);
        _draw(j);
        _draw(jB);
        _assignProofBatch(j);
        _judgeProof(j, uint8(FairBindCore.Verdict.PASS));
        _judgeProof(jB, uint8(FairBindCore.Verdict.FAIL));
        uint32 bondA = _bondOfSeller(sellerId);
        (bool distributed,) = address(fairbind).call(abi.encodeCall(fb.distributeCompensation, (bondA)));
        if (!distributed) return true;
        (bool paid,) = address(fairbind).call(abi.encodeCall(fb.claimCompensation, (j)));
        return !paid;
    }

    function test_poolStaysWithItsAccount() public {
        require(_poolStaysWithItsAccount(proofArtifact), "per account");
    }

    function test_sharedPoolIsCaught() public {
        require(!_poolStaysWithItsAccount("BatchMutants.sol:SharedPoolProof"), "mutation caught");
    }

    /// The pool is split by value: entries of 0.01 and 0.005 USDC share a
    /// pool of 15,000 base units as 10,000 and 5,000. A seller's own buyer shares
    /// like any other: the pool bounds what it can take back.
    function test_poolIsSplitInProportionToValue() public {
        _deployBatched(_proofProfile(), _proofTerms(1_000_000, 0), _equalBonds());
        hv.roll(10);
        d = _purchase(G);
        j = _purchase(G);
        k = _purchase(G);
        bytes32 m = _purchase(G / 2);
        _unserved(d);
        delete epoch0;
        epoch0.push(d);
        epoch0.push(j);
        epoch0.push(k);
        epoch0.push(m);
        _anchorOf(0, sellerId, SELLER_OWNER, epoch0);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(j);
        _openSample(k);
        _openSample(m);
        _assignBatch(0);
        _pass(j);
        _pass(k);
        _pass(m);
        _final(j);
        _final(k);
        _final(m);
        _submit(j);
        _submit(k);
        _submit(m);
        _draw(j);
        _draw(k);
        _draw(m);
        _assignProofBatch(j);
        _judgeProof(j, uint8(FairBindCore.Verdict.FAIL));
        _judgeProof(k, uint8(FairBindCore.Verdict.PASS));
        _judgeProof(m, uint8(FairBindCore.Verdict.PASS));
        uint32 bondId = _bondOfSeller(sellerId);
        require(fb.getPool(bondId).balance == 15_000 && fb.getPool(bondId).weight == G + G / 2, "pool and weight");
        hv.prank(KEEPER);
        fb.distributeCompensation(bondId);
        uint256 b0 = token.balanceOf(buyer);
        fb.claimCompensation(k);
        require(token.balanceOf(buyer) - b0 == 10_000, "two thirds");
        b0 = token.balanceOf(buyer);
        fb.claimCompensation(m);
        require(token.balanceOf(buyer) - b0 == 5_000, "one third");
    }
}
