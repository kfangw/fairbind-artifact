// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeShared } from "../src/modules/ExchangeShared.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { Mock1271Wallet } from "./ExchangeMocks.sol";

/// Receipt signatures (ADR 0037, rule D2-33 (a') (b) (c) (g)): only the
/// seller posts them, one per nonce, signed with its registered key; a sale
/// is a purchase whose posted leaf matched the anchor by A_e; any other
/// purchase is refunded.
contract ReceiptExchangeTest is ExchangeBase {
    uint256 internal constant OTHER_KEY = 0x0DD;

    function _start() internal {
        _deployDefault();
        hv.roll(10);
    }

    function postExternal(ExchangeStore.Post memory q, bytes memory sellerSig) external {
        fx.postReceipt(q, sellerSig);
    }

    function test_postListSkipsOnlyTheFailingNonces() public {
        _start();
        bytes32 a = _buy();
        bytes32 b = _buy();
        bytes32 c = _buy();
        ExchangeStore.Post[] memory list = new ExchangeStore.Post[](4);
        list[0] = _post(a, _bundle(a), BUYER_KEY);
        list[1] = _post(b, _bundle(b), OTHER_KEY);
        list[2] = _post(c, _bundle(c), BUYER_KEY);
        list[3] = _post(a, bundleOf[a], BUYER_KEY);
        list[3].nonce = keccak256("no purchase");
        bytes memory items;
        for (uint256 i; i < 4; i++) {
            items = abi.encodePacked(items, abi.encode(list[i].nonce, list[i].ctHash, list[i].ekHash, list[i].rHash, list[i].leaf));
        }
        bytes memory sig = _sig(SELLER_KEY, fx.postListDigest(PROFILE, keccak256(items), 4));
        fx.postReceipts(list, sig);
        (bytes32 ha,,) = fx.getExchangeRecord(a);
        (bytes32 hb,,) = fx.getExchangeRecord(b);
        (bytes32 hc,,) = fx.getExchangeRecord(c);
        require(ha != 0 && hc != 0 && hb == 0, "a and c posted, b skipped");
        // The single posting of the list's first item is another digest.
        hv.expectRevert(FairBindCore.InvalidSignature.selector);
        this.postExternal(list[1], sig);
        _postSigned(b);
        (hb,,) = fx.getExchangeRecord(b);
        require(hb != 0, "b posted alone");
    }

    function test_postingNeedsTheRegisteredSellerKey() public {
        require(_thirdPartyRefused(""), "refused");
    }

    function test_postingByAnyoneIsCaught() public {
        require(!_thirdPartyRefused("ExchangeMutants.sol:AnyPosterExchange"), "mutation caught");
    }

    /// A buyer and a third party X sign a bundle of their own for the
    /// buyer's purchase and post it first, with X's posting signature.
    function _thirdPartyRefused(string memory ex) internal returns (bool) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _start();
        bytes32 n = _buy();
        Bundle memory fake = _bundleWith(n, keccak256("fake key"), _pad(bytes("1")), fx.proofCommitment(n));
        ExchangeStore.Post memory q = _post(n, fake, BUYER_KEY);
        bytes memory xSig = _sig(OTHER_KEY, fx.postDigest(q));
        try this.postExternal(q, xSig) {
            return false;
        } catch (bytes memory err) {
            (bytes32 h,,) = fx.getExchangeRecord(n);
            return bytes4(err) == FairBindCore.InvalidSignature.selector && h == 0;
        }
    }

    function test_buyerSignatureNamesTheRegisteredSeller() public {
        _start();
        bytes32 n = _buy();
        Bundle memory b = _bundle(n);
        // The buyer signed a digest that names another seller address.
        bytes32 structHash = keccak256(
            abi.encode(
                keccak256(
                    "FairBindReceiptSignature(address seller,bytes32 nonce,bytes32 ctHash,bytes32 ekHash,bytes32 responseHash,bytes32 leaf)"
                ),
                hv.addr(OTHER_KEY), n, b.ctHash, b.ekHash, b.rHash, b.leaf
            )
        );
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract,bytes32 salt)"),
                keccak256("FairBind"), keccak256("1"), block.chainid, address(fairbind), keccak256("profile")
            )
        );
        ExchangeStore.Post memory q = ExchangeStore.Post(n, b.ctHash, b.ekHash, b.rHash, b.leaf, "");
        q.buyerSig = _sig(BUYER_KEY, keccak256(abi.encodePacked(hex"1901", domain, structHash)));
        fx.postReceipt(q, _sig(SELLER_KEY, fx.postDigest(q)));
        (bytes32 h,,) = fx.getExchangeRecord(n);
        require(h == 0, "skipped");
    }

    function test_secondBundleOfANonceIsDropped() public {
        require(_secondBundleDropped(""), "dropped");
    }

    function test_secondBundleReplacingTheFirstIsCaught() public {
        require(!_secondBundleDropped("ExchangeMutants.sol:RepostExchange"), "mutation caught");
    }

    /// The buyer signs two bundles of one nonce (a double signature); the
    /// seller posts the first. The second posting, of the other bundle,
    /// keeps the first, and only the first bundle's key proves the purchase.
    function _secondBundleDropped(string memory ex) internal returns (bool) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _start();
        bytes32 n = _buy();
        Bundle memory first = _bundle(n);
        Bundle memory second = _bundleWith(n, keccak256("second key"), _pad(RESPONSE), fx.proofCommitment(n));
        ExchangeStore.Post memory q1 = _post(n, first, BUYER_KEY);
        ExchangeStore.Post memory q2 = _post(n, second, BUYER_KEY);
        fx.postReceipt(q1, _sig(SELLER_KEY, fx.postDigest(q1)));
        (bytes32 h1,,) = fx.getExchangeRecord(n);
        fx.postReceipt(q2, _sig(SELLER_KEY, fx.postDigest(q2)));
        (bytes32 h2,,) = fx.getExchangeRecord(n);
        if (h2 != h1) return false;
        hv.prank(buyer);
        fx.openProofDispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        ExchangeStore.PassProof memory p2 = ExchangeStore.PassProof(second.ek, second.ct, 1, _canonical(n), "", "");
        try this.proveExternal(n, 0, p2) {
            return false;
        } catch { }
        _prove(n, 0);
        return _record(n).disputeState == ExchangeStore.DISPUTE_PASSED;
    }

    function test_lateMatchIsRefusedAndThePurchaseRefunded() public {
        require(_lateMatchRefused(""), "refused");
    }

    function test_lateMatchAcceptedIsCaught() public {
        require(!_lateMatchRefused("ExchangeMutants.sol:LateMatchExchange"), "mutation caught");
    }

    function matchExternal(bytes32 n) external {
        _matchAll(_one(n));
    }

    function _lateMatchRefused(string memory ex) internal returns (bool) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        _anchorX(0, _one(n));
        hv.roll(701);
        try this.matchExternal(n) {
            return false;
        } catch (bytes memory err) {
            if (bytes4(err) != FairBindCore.DeadlinePassed.selector) return false;
        }
        _sealX(0);
        hv.expectRevert(FairBindCore.NotBound.selector);
        fx.openProofSample(n);
        uint256 before = token.balanceOf(buyer);
        fx.refundUnbound(n);
        fairbind.claimRefund(n);
        return token.balanceOf(buyer) == before + 10_000;
    }

    function test_unboundPurchaseIsRefundedOnceAndNeverReleased() public {
        _start();
        bytes32 n = _buy();
        bytes32 m = _buy();
        _postSigned(m);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fx.refundUnbound(n);
        _anchorX(0, _two(n, m));
        _matchAll(_one(m));
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.matchExternal(n);
        _sealX(0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fx.refundUnbound(m);
        fx.refundUnbound(n);
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refund due");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "once");
        hv.expectRevert(FairBindCore.AlreadyFinalized.selector);
        fx.refundUnbound(n);
        require(_bond().failureCount == 0, "no failure");
        // m is a sale; n never reaches the seller.
        fx.openProofSample(m);
        _prove(m, 0);
        hv.roll(40_011);
        fairbind.releasePurchase(m);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
    }

    /// A smart-account buyer: its receipt signature is checked through
    /// ERC-1271 when posted; revoking the signature later changes nothing.
    function test_smartAccountSignatureHoldsAfterRevocation() public {
        _start();
        Mock1271Wallet w = new Mock1271Wallet(hv.addr(BUYER_KEY));
        token.setVerifySignatures(false);
        token.mint(address(w), 1_000_000);
        buyer = address(w);
        bytes32 n = _buy();
        bytes32 m = _buy();
        Bundle memory bn = _bundle(n);
        Bundle memory bm = _bundle(m);
        ExchangeStore.Post[] memory list = new ExchangeStore.Post[](2);
        list[0] = _post(n, bn, BUYER_KEY);
        list[1] = _post(m, bm, BUYER_KEY);
        // A 1271 call that spends its whole cap answers nothing: m is skipped.
        w.setBurn(60_000);
        _postList(list);
        (bytes32 hn,,) = fx.getExchangeRecord(n);
        require(hn == 0, "n skipped while the account burns its cap");
        w.setBurn(0);
        _postList(list);
        (hn,,) = fx.getExchangeRecord(n);
        (bytes32 hm,,) = fx.getExchangeRecord(m);
        require(hn != 0 && hm != 0, "both posted");
        w.setRevoked(true);
        _anchorX(0, _two(n, m));
        _matchAll(_two(n, m));
        require(_bound(n) && _bound(m), "bound after the revocation");
    }

    function _postList(ExchangeStore.Post[] memory list) internal {
        bytes memory items;
        for (uint256 i; i < list.length; i++) {
            items = abi.encodePacked(items, abi.encode(list[i].nonce, list[i].ctHash, list[i].ekHash, list[i].rHash, list[i].leaf));
        }
        fx.postReceipts(list, _sig(SELLER_KEY, fx.postListDigest(PROFILE, keccak256(items), list.length)));
    }

    function postListExternal(ExchangeStore.Post[] memory list, uint256 gas) external {
        bytes memory items;
        for (uint256 i; i < list.length; i++) {
            items = abi.encodePacked(items, abi.encode(list[i].nonce, list[i].ctHash, list[i].ekHash, list[i].rHash, list[i].leaf));
        }
        bytes memory sig = _sig(SELLER_KEY, fx.postListDigest(PROFILE, keccak256(items), list.length));
        (bool ok, bytes memory ret) =
            address(fairbind).call{ gas: gas }(abi.encodeWithSelector(fx.postReceipts.selector, list, sig));
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }

    /// Too little gas for the 1271 cap reverts the whole posting, so a payer
    /// cannot starve the call into skipping a nonce.
    function test_postingWithoutGasForThe1271CapReverts() public {
        _start();
        Mock1271Wallet w = new Mock1271Wallet(hv.addr(BUYER_KEY));
        token.setVerifySignatures(false);
        token.mint(address(w), 1_000_000);
        buyer = address(w);
        bytes32 n = _buy();
        ExchangeStore.Post[] memory list = new ExchangeStore.Post[](1);
        list[0] = _post(n, _bundle(n), BUYER_KEY);
        hv.expectRevert(ExchangeShared.GasBelow1271Bound.selector);
        this.postListExternal(list, 60_000);
        (bytes32 h,,) = fx.getExchangeRecord(n);
        require(h == 0, "nothing kept");
        this.postListExternal(list, 400_000);
        (h,,) = fx.getExchangeRecord(n);
        require(h != 0, "posted with gas for the cap");
    }

    /// A seller whose signing key is a smart account: its 1271 posting
    /// signature beyond L_sig is refused.
    function test_sellerSignatureBeyondItsLengthBoundIsRefused() public {
        _start();
        bytes32 n = _buy();
        ExchangeStore.Post memory q = _post(n, _bundle(n), BUYER_KEY);
        bytes memory longSig = new bytes(300);
        hv.expectRevert(FairBindCore.InvalidSignature.selector);
        fx.postReceipt(q, longSig);
    }

    /// A split anchor: a nonce of the second unit matches against that unit.
    function test_matchInTheUnitOfASplitAnchor() public {
        _start();
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) {
            ns[i] = _buy();
            _postSigned(ns[i]);
        }
        _xTree(ns);
        hv.roll(600);
        // Units of two entries: the first two sorted entries, then the third.
        FairBindMerkle.ReceiptEntry[] memory u0 = new FairBindMerkle.ReceiptEntry[](2);
        u0[0] = FairBindMerkle.ReceiptEntry(xs[0], leafOf[xs[0]]);
        u0[1] = FairBindMerkle.ReceiptEntry(xs[1], leafOf[xs[1]]);
        FairBindMerkle.ReceiptEntry[] memory u1 = new FairBindMerkle.ReceiptEntry[](1);
        u1[0] = FairBindMerkle.ReceiptEntry(xs[2], leafOf[xs[2]]);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 1, u0, keccak256("publication"));
        // Unit 0 is up: its first entry matches against the unit root now.
        Bundle storage b0 = bundleOf[xs[0]];
        bytes32[] memory path = new bytes32[](1);
        path[0] = keccak256(abi.encode(LEAF_DOMAIN, xs[1], leafOf[xs[1]]));
        ExchangeStore.Match[] memory ms = new ExchangeStore.Match[](1);
        ms[0] = ExchangeStore.Match(xs[0], b0.ctHash, b0.ekHash, b0.rHash, b0.leaf, 0, 0, path);
        fx.matchAnchor(ms);
        require(_bound(xs[0]), "matched in unit 0 before the anchor completes");
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 1, u1, keccak256("publication"));
        Bundle storage b2 = bundleOf[xs[2]];
        ms[0] = ExchangeStore.Match(xs[2], b2.ctHash, b2.ekHash, b2.rHash, b2.leaf, 1, 0, new bytes32[](0));
        fx.matchAnchor(ms);
        require(_bound(xs[2]), "matched in unit 1");
    }

    // ------------------------------------- a posting carried by a PASS proof

    /// A PASS proof that carries the posting (rule D2-33 (e'), N14-6) posts
    /// the receipt signature as postReceipt would, and binds nothing by
    /// itself: a purchase binds only by a match with the anchor within A_e.
    function _proveCarrying(bytes32 x) internal {
        ExchangeStore.PassProof memory q = _passProof(x);
        ExchangeStore.Post memory post = _post(x, bundleOf[x], BUYER_KEY);
        q.buyerSig = post.buyerSig;
        q.sellerSig = _sig(SELLER_KEY, fx.postDigest(post));
        fx.prove(x, 0, q);
    }

    function matchOfExternal(ExchangeStore.Match memory m) external {
        ExchangeStore.Match[] memory ms = new ExchangeStore.Match[](1);
        ms[0] = m;
        fx.matchAnchor(ms);
    }

    function test_postingInAProofBindsOnlyByAMatch() public {
        _start();
        bytes32 n = _buy();
        bytes32 m = _buy();
        bytes32 k = _buy();
        _bundle(n);
        _bundle(k);
        Bundle memory bm = _bundle(m);
        // m's anchored leaf is not the leaf its buyer signed.
        bytes32 other = keccak256(abi.encode("another leaf", m));
        leafOf[m] = other;
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = n;
        ns[1] = m;
        ns[2] = k;
        _anchorX(0, ns);
        // After the anchor, before A_e: three proofs carry the postings.
        _proveCarrying(n);
        _proveCarrying(m);
        _proveCarrying(k);
        require(_record(n).proven && _record(m).proven && _record(k).proven, "proven");
        require(!_bound(n) && !_bound(m) && !_bound(k), "posted, not bound");
        // m: neither the signed leaf on the anchored path nor the anchored
        // leaf against the posted bundle matches.
        ExchangeStore.Match memory mm = _matchOf(m);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.matchOfExternal(mm);
        mm.leaf = other;
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        this.matchOfExternal(mm);
        require(bm.leaf != other, "two leaves");
        // k matches within A_e; n is never matched.
        _matchAll(_one(k));
        require(_bound(k), "k bound by its match");
        hv.roll(701);
        _sealX(0);
        hv.expectRevert(FairBindCore.NotBound.selector);
        fx.openProofSample(n);
        hv.expectRevert(FairBindCore.NotBound.selector);
        fx.openProofSample(m);
        fx.refundUnbound(n);
        fx.refundUnbound(m);
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "n refunded");
        require(_fs(m) == uint8(FairBindCore.FinancialState.REFUNDABLE), "m refunded");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fx.refundUnbound(k);
        fx.openProofSample(k);
        require(_state(k) == uint8(FairBindCore.CaseState.FINAL), "k: its PASS proof ends the case");
    }
}
