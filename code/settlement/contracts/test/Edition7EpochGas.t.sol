// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";

/// Call gas of one seller epoch of eight purchases on a receipt-signature
/// vote profile under edition 7: settle, the receipt posting of one sale,
/// the anchor, the match of the eight sales, the seal and the release of one
/// sale. It uses only calls that exist before rule edition 8, so the same
/// file measures both builds (the rule 8 counterpart is Rule8Gas.t.sol).
/// Run with --isolate. Every number is logged; nothing is asserted about gas.
contract Edition7EpochGasTest is ExchangeBase {
    uint256 internal N = 8;

    function _selecting(uint24 epoch, bytes32[] memory ns) internal view returns (bytes32 h) {
        uint256 ppm = fairbind.getServiceProfile(PROFILE).parameters.samplePpm;
        uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
        for (uint256 salt;; salt++) {
            h = keccak256(abi.encode("beacon", epoch, salt));
            bool any;
            for (uint256 i; i < ns.length; i++) {
                uint256 v = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, ns[i])));
                if (v < threshold) any = true;
            }
            if (!any) return h;
        }
    }

    /// The same epoch with 32 purchases (anchor and match slope).
    function test_gas_edition7Epoch32() public {
        N = 32;
        test_gas_edition7Epoch();
    }

    function test_gas_edition7Epoch() public {
        mode = ExchangeStore.MODE_VOTE_SIG;
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.samplePpm = 40_000;
        p.effectivePpm = 40_000;
        _deployWith(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](N);
        uint256 g = gasleft();
        ns[0] = _buy();
        _log("settle (first of the account) gas", g - gasleft());
        g = gasleft();
        ns[1] = _buy();
        _log("settle (second) gas", g - gasleft());
        for (uint256 i = 2; i < N; i++) {
            // The bucket holds 20 settlements and refills one per 20 blocks.
            if (i >= 20) hv.roll(_now() + 20);
            ns[i] = _buy();
        }
        ExchangeStore.Post memory q = _post(ns[0], _bundle(ns[0]), BUYER_KEY);
        bytes memory sig = _sig(SELLER_KEY, fx.postDigest(q));
        g = gasleft();
        fx.postReceipt(q, sig);
        _log("edition 7: postReceipt (one sale) gas", g - gasleft());
        for (uint256 i = 1; i < N; i++) _postSigned(ns[i]);
        _xTree(ns);
        hv.roll(600);
        FairBindMerkle.ReceiptEntry[] memory list = _xEntries();
        g = gasleft();
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, list, uint32(N), keccak256("publication"));
        _log(N == 8 ? "edition 7: anchor (8 entries) gas" : "edition 7: anchor (32 entries) gas", g - gasleft());
        ExchangeStore.Match[] memory ms = new ExchangeStore.Match[](N);
        for (uint256 i; i < N; i++) ms[i] = _matchOf(ns[i]);
        g = gasleft();
        fx.matchAnchor(ms);
        _log(N == 8 ? "edition 7: matchAnchor (8 sales) gas" : "edition 7: matchAnchor (32 sales) gas", g - gasleft());
        uint256 rb = 1469;
        hv.roll(rb + 1);
        hv.setBlockhash(rb, _selecting(0, ns));
        g = gasleft();
        fairbind.seal(sellerId, 0);
        _log("edition 7: seal (per seller epoch) gas", g - gasleft());
        hv.roll(200_000);
        g = gasleft();
        fairbind.releasePurchase(ns[0]);
        _log("edition 7: releasePurchase (one sale) gas", g - gasleft());
        g = gasleft();
        fairbind.releasePurchase(ns[1]);
        _log("edition 7: releasePurchase (one sale, warm account) gas", g - gasleft());
    }
}
