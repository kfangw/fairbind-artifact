// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { IUniquePriceUpdates } from "../src/oracle/IUniquePriceUpdates.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";
import { CostProbe } from "./ExchangeMutants.sol";
import { MultiCall } from "./ExchangeMocks.sol";

/// Call-frame gas of the receipt-signature and proof paths (ADR 0037): the
/// posting of one and of several receipt signatures, the anchor match, the
/// PASS proof at several padded lengths with its decryption, the key
/// dispute with its measured cost, the cost measurement itself, the vote
/// ladder under measured costs, and the seller's proof. Run with --isolate.
/// Every number is logged; nothing is asserted about gas. The price-update
/// check runs in a test verifier: its own gas is logged apart so that the
/// measured gas of the real verifier can take its place.
contract ExchangeGasTest is ExchangeBase {
    function _g(string memory label, uint256 gas) internal view {
        _log(label, gas);
    }

    function _start() internal {
        _deployDefault();
        hv.roll(10);
    }

    function _items(ExchangeStore.Post[] memory list) internal pure returns (bytes memory items) {
        for (uint256 i; i < list.length; i++) {
            items = abi.encodePacked(items, abi.encode(list[i].nonce, list[i].ctHash, list[i].ekHash, list[i].rHash, list[i].leaf));
        }
    }

    function _postList(uint256 k, string memory label) internal returns (bytes32[] memory ns) {
        ns = new bytes32[](k);
        ExchangeStore.Post[] memory list = new ExchangeStore.Post[](k);
        for (uint256 i; i < k; i++) {
            ns[i] = _buy();
            list[i] = _post(ns[i], _bundle(ns[i]), BUYER_KEY);
            posted.push(ns[i]);
        }
        bytes memory sig = _sig(SELLER_KEY, fx.postListDigest(PROFILE, keccak256(_items(list)), k));
        uint256 g = gasleft();
        fx.postReceipts(list, sig);
        g -= gasleft();
        _g(label, g);
        _g(string.concat(label, " per signature"), g / k);
    }

    // ------------------------------------------------------------ posting

    function test_gas_postOne() public {
        _start();
        bytes32 n = _buy();
        ExchangeStore.Post memory q = _post(n, _bundle(n), BUYER_KEY);
        bytes memory sig = _sig(SELLER_KEY, fx.postDigest(q));
        uint256 g = gasleft();
        fx.postReceipt(q, sig);
        _g("postReceipt (one signature) gas", g - gasleft());
    }

    function test_gas_postLists() public {
        _start();
        _postList(1, "postReceipts, 1 signature gas");
        _postList(4, "postReceipts, 4 signatures gas");
        _postList(12, "postReceipts, 12 signatures gas");
    }

    function test_gas_settleUnderAProofProfile() public {
        _start();
        uint256 g = gasleft();
        _buy();
        _g("settle under a proof profile (first of the account) gas", g - gasleft());
        g = gasleft();
        _buy();
        _g("settle under a proof profile (second) gas", g - gasleft());
    }

    // -------------------------------------------------------------- match

    function test_gas_match() public {
        _start();
        bytes32[] memory ns = new bytes32[](16);
        for (uint256 i; i < 16; i++) {
            ns[i] = _buy();
            _postSigned(ns[i]);
        }
        _anchorX(0, ns);
        ExchangeStore.Match[] memory one = new ExchangeStore.Match[](1);
        one[0] = _matchOf(ns[0]);
        uint256 g = gasleft();
        fx.matchAnchor(one);
        _g("matchAnchor, 1 nonce of 16 (path 4) gas", g - gasleft());
        ExchangeStore.Match[] memory four = new ExchangeStore.Match[](4);
        for (uint256 i; i < 4; i++) four[i] = _matchOf(ns[1 + i]);
        g = gasleft();
        fx.matchAnchor(four);
        g -= gasleft();
        _g("matchAnchor, 4 nonces of 16 gas", g);
        _g("matchAnchor, 4 nonces of 16 per nonce", g / 4);
    }

    function test_gas_refundUnbound() public {
        _start();
        bytes32 n = _buy();
        _anchorX(0, _one(n));
        hv.roll(701);
        uint256 g = gasleft();
        fx.refundUnbound(n);
        _g("refundUnbound gas", g - gasleft());
    }

    // --------------------------------------------------------- PASS proof

    function _sampleProof(uint16 lr) internal {
        padLen = lr;
        _start();
        bytes32 n = _buy();
        _bindAndSeal(_one(n));
        uint256 g = gasleft();
        fx.openProofSample(n);
        _g(string.concat("openProofSample (L_r ", _str(lr), ") gas"), g - gasleft());
        ExchangeStore.PassProof memory q = _passProof(n);
        g = gasleft();
        fx.prove(n, 0, q);
        _g(string.concat("prove, sample case, L_r ", _str(lr), " gas"), g - gasleft());
        _g(string.concat("prove, sample case, L_r ", _str(lr), " calldata bytes"), abi.encodeWithSelector(fx.prove.selector, n, uint8(0), q).length);
    }

    function test_gas_proveSample64() public {
        _sampleProof(64);
    }

    function test_gas_proveSample256() public {
        _sampleProof(256);
    }

    function test_gas_proveSample1024() public {
        _sampleProof(1024);
    }

    /// The test verifier's own gas for the same update, called directly.
    function test_gas_testVerifierAlone() public {
        _start();
        bytes32 n = _buy();
        bytes[] memory data = new bytes[](1);
        data[0] = _canonical(n);
        bytes32[] memory ids = new bytes32[](1);
        ids[0] = FEED;
        uint64 t = _record(n).refTime;
        uint256 g = gasleft();
        feed.parsePriceFeedUpdatesUnique(data, ids, t, type(uint64).max);
        _g("test verifier parse (call included) gas", g - gasleft());
    }

    function test_gas_keyDispute() public {
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        hv.prank(buyer);
        uint256 g = gasleft();
        fx.openProofDispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        _g("openProofDispute gas", g - gasleft());
        ExchangeStore.PassProof memory q = _passProof(n);
        g = gasleft();
        fx.prove(n, 0, q);
        _g("prove, key dispute (measured cost and share), L_r 64 gas", g - gasleft());
    }

    /// The same proof without a dispute (a PASS proof of a purchase with no
    /// open case, kept for the seller's proof): the difference to the key
    /// dispute is the measurement and the deposit split.
    function test_gas_proveWithoutAnOpenCase() public {
        _start();
        bytes32 n = _buy();
        _postSigned(n);
        ExchangeStore.PassProof memory q = _passProof(n);
        uint256 g = gasleft();
        fx.prove(n, 0, q);
        _g("prove, no open case, L_r 64 gas", g - gasleft());
    }

    function test_gas_keyDisputeWithThePostingInTheProof() public {
        _start();
        bytes32 n = _buy();
        Bundle memory b = _bundle(n);
        hv.prank(buyer);
        fx.openProofDispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        ExchangeStore.PassProof memory q = _passProof(n);
        ExchangeStore.Post memory post = _post(n, b, BUYER_KEY);
        q.buyerSig = post.buyerSig;
        q.sellerSig = _sig(SELLER_KEY, fx.postDigest(post));
        uint256 g = gasleft();
        fx.prove(n, 0, q);
        _g("prove, key dispute with the posting in the proof gas", g - gasleft());
    }

    function test_gas_failurePaths() public {
        _start();
        bytes32 n = _buy();
        bytes32 m = _buy();
        _bindAndSeal(_two(n, m));
        fx.openProofSample(n);
        fx.openProofSample(m);
        uint64 t = _record(n).refTime;
        bytes memory upd = _update(t + 11, t - 1, PRICE);
        uint256 g = gasleft();
        fx.proveAbsence(n, upd);
        _g("proveAbsence (sample case, first failure) gas", g - gasleft());
        hv.roll(fairbind.getCase(m).judgeDue + 1);
        g = gasleft();
        fx.timeoutProof(m);
        _g("timeoutProof (sample case, second failure) gas", g - gasleft());
    }

    // ---------------------------------------------------- seller's proof

    function test_gas_selfProof() public {
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
        uint256 g = gasleft();
        fx.selfProve(b);
        _g("selfProve (confirmed at once) gas", g - gasleft());
        hv.roll(uint256(fairbind.getPurchase(b).retainUntil) + 1);
        g = gasleft();
        fx.releaseSelfProven(b);
        _g("releaseSelfProven gas", g - gasleft());
    }

    // ------------------------------------------------- vote ladder costs

    function _ladder(bool costs) internal {
        mode = ExchangeStore.MODE_NONE;
        _deployExchange(_productionProfile(), _input(0), costs);
        hv.roll(10);
        bytes32 n = _buy();
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.prank(SELLER_OWNER);
        uint256 g = gasleft();
        fairbind.served(n, keccak256("bundle"));
        _g(costs ? "served, measured gas" : "served, without cost terms gas", g - gasleft());
    }

    function test_gas_servedMeasured() public {
        _ladder(true);
    }

    function test_gas_servedUnmeasured() public {
        _ladder(false);
    }

    function test_gas_discloseKey() public {
        mode = ExchangeStore.MODE_VOTE_SIG;
        _deployDefault();
        hv.roll(10);
        bytes32 n = _buy();
        _postSigned(n);
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        Bundle memory b = bundleOf[n];
        hv.prank(SELLER_OWNER);
        uint256 g = gasleft();
        fx.discloseKey(n, false, b.ek, b.ct, b.leaf);
        _g("discloseKey (vote profile, measured) gas", g - gasleft());
    }

    function _str(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        bytes memory b;
        while (v != 0) {
            b = abi.encodePacked(bytes1(uint8(48 + v % 10)), b);
            v /= 10;
        }
        return string(b);
    }

    // ---------------------------------------- vote with receipt signatures

    function test_gas_voteSignaturePath() public {
        mode = ExchangeStore.MODE_VOTE_SIG;
        _deployDefault();
        hv.roll(10);
        bytes32 n = _buy();
        ExchangeStore.Post memory q = _post(n, _bundle(n), BUYER_KEY);
        bytes memory sig = _sig(SELLER_KEY, fx.postDigest(q));
        uint256 g = gasleft();
        fx.postReceipt(q, sig);
        _g("vote: postReceipt (one signature) gas", g - gasleft());
        _postList(4, "vote: postReceipts, 4 signatures gas");
        bytes32 u = _buy();
        bytes32[] memory ns = new bytes32[](7);
        ns[0] = n;
        for (uint256 i; i < 4; i++) ns[1 + i] = xsList(i);
        ns[5] = u;
        ns[6] = _buy();
        _anchorX(0, ns);
        ExchangeStore.Match[] memory one = new ExchangeStore.Match[](1);
        one[0] = _matchOf(n);
        g = gasleft();
        fx.matchAnchor(one);
        _g("vote: matchAnchor, 1 nonce of 7 gas", g - gasleft());
        hv.roll(701);
        g = gasleft();
        fx.refundUnbound(u);
        _g("vote: refundUnbound gas", g - gasleft());
    }

    bytes32[] internal posted;

    function xsList(uint256 i) internal view returns (bytes32) {
        return posted[i];
    }

    function test_gas_voteNonDeliveryRefund() public {
        mode = ExchangeStore.MODE_VOTE_SIG;
        _deployDefault();
        hv.roll(10);
        bytes32 n = _buy();
        _postSigned(n);
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        uint256 g = gasleft();
        fairbind.timeoutServe(n);
        _g("vote: timeoutServe, non-delivery refund without failure gas", g - gasleft());
    }

    function test_gas_voteNonDeliveryFailureWithoutSignatures() public {
        mode = ExchangeStore.MODE_NONE;
        _deployDefault();
        hv.roll(10);
        bytes32 n = _buy();
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        uint256 g = gasleft();
        fairbind.timeoutServe(n);
        _g("vote without signatures: timeoutServe, confirmed failure gas", g - gasleft());
    }

    /// The test L1 fee oracle's own gas for inputs of the measured sizes, so
    /// that the gas of the chain's oracle can take its place.
    function test_gas_testOracleAlone() public {
        _start();
        bytes memory small = new bytes(168);
        bytes memory large = new bytes(968);
        for (uint256 i; i < large.length; i++) large[i] = bytes1(uint8(i | 1));
        uint256 g = gasleft();
        oracle.getL1Fee(small);
        _g("test L1 oracle, 168 bytes (call included) gas", g - gasleft());
        g = gasleft();
        oracle.getL1Fee(large);
        _g("test L1 oracle, 968 bytes (call included) gas", g - gasleft());
    }

    /// The test oracle's getL1FeeUpperBound for the lengths of the measured
    /// calls plus bEnv (100): its own gas, so that the chain's can take its
    /// place.
    function test_gas_testOracleBoundAlone() public {
        _start();
        uint256 g = gasleft();
        oracle.getL1FeeUpperBound(268);
        _g("test L1 oracle bound, 168 + 100 bytes (call included) gas", g - gasleft());
        g = gasleft();
        oracle.getL1FeeUpperBound(1068);
        _g("test L1 oracle bound, 968 + 100 bytes (call included) gas", g - gasleft());
    }

    /// The measured cost itself on a 968-byte call data (the key dispute's
    /// proof at L_r 64 is 868 bytes; 968 is the G_oracle length), first and
    /// later call of a transaction, in the bound form. The oracle is the
    /// test oracle; its gas (test_gas_testOracleBoundAlone) is to be
    /// replaced by the chain's.
    function test_gas_measuredCostItself() public {
        _start();
        bytes memory x = new bytes(968);
        for (uint256 i; i < x.length; i++) x[i] = bytes1(uint8(i | 1));
        address[5] memory a = [address(0x1001), address(0x1002), address(0x1003), address(0x1004), address(0x1005)];
        CostProbe probe = new CostProbe(a[0], a[1], a[2], a[3], a[4]);
        probe.setCostTerms(4_000_000_000, 21_000, 12_000, 100);
        (uint256 g1, uint256 g2, uint256 c1, uint256 c2) = probe.measureGas(x);
        _g("measured cost itself, bound form, 968 bytes, first call gas", g1);
        _g("measured cost itself, bound form, 968 bytes, later call gas", g2);
        _g("  first cost (token units)", c1);
        _g("  later cost (token units)", c2);
    }

    /// Two key-dispute proofs in one transaction: the second takes the
    /// second-call L1 share (two oracle calls).
    function test_gas_twoKeyDisputesInOneTransaction() public {
        _start();
        bytes32 a = _buy();
        _postSigned(a);
        bytes32 b = _buy();
        _postSigned(b);
        hv.prank(buyer);
        fx.openProofDispute(a, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        hv.prank(buyer);
        fx.openProofDispute(b, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        MultiCall m = new MultiCall();
        bytes[] memory calls = new bytes[](2);
        calls[0] = abi.encodeWithSelector(fx.prove.selector, a, uint8(0), _passProof(a));
        calls[1] = abi.encodeWithSelector(fx.prove.selector, b, uint8(0), _passProof(b));
        uint256 g = gasleft();
        m.run(address(fairbind), calls);
        _g("two key-dispute proofs in one transaction (MultiCall) gas", g - gasleft());
    }
}
