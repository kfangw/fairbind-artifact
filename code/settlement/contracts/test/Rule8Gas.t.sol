// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { Rule8Store } from "../src/modules/Rule8Store.sol";
import { FairBindRule8 } from "../src/modules/FairBindRule8.sol";
import { Rule8Base } from "./Rule8Base.sol";

/// Call gas of one seller epoch of eight purchases on a receipt-signature
/// vote profile under rule 8 (its edition 7 counterpart is
/// Edition7EpochGas.t.sol) (seller-signed bulk anchor, profile seal, release unit of
/// eight, cursor). Run with --isolate: each call is one transaction with its
/// 21,000 base and cold slots. Every number is logged; nothing is asserted
/// about gas. No purchase is sampled, so the release paths are those of
/// unsampled sales.
contract Rule8GasTest is Rule8Base {
    uint256 internal N = 8;

    function _r8Input() internal view override returns (Rule8Store.Input memory x) {
        x = super._r8Input();
        x.unitLog2 = N == 8 ? 3 : 5;
        x.bulkSig = true;
    }

    function _deployGas() internal {
        _deployR8Mode(ExchangeStore.MODE_VOTE_SIG, 40_000);
    }

    function _buyN() internal returns (bytes32[] memory ns) {
        ns = new bytes32[](N);
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
    }

    function test_gas_rule8Epoch() public {
        _deployGas();
        bytes32[] memory ns = _buyN();
        bool[] memory bound = new bool[](N);
        for (uint256 i; i < N; i++) {
            keyOf[ns[i]] = BUYER_KEY;
            bound[i] = true;
        }
        BulkAnchor memory x = _bulkAnchor(0, ns, bound);
        bytes memory sig = _sig(SELLER_KEY, r8.anchorDigest(x.content));
        hv.roll(600);
        uint256 g = gasleft();
        r8.anchorBulk(x.content, x.entries, sig);
        _log(N == 8 ? "rule 8: anchorBulk (8 entries, 8 buyer signatures checked) gas" : "rule 8: anchorBulk (32 entries, 32 buyer signatures checked) gas", g - gasleft());
        uint256 rb = _valueBlockOf(0);
        hv.roll(rb + 1);
        hv.setBlockhash(rb, _beaconSelecting(0, ns, 0));
        g = gasleft();
        r8.sealProfile(PROFILE, 0);
        _log("rule 8: sealProfile (per profile epoch) gas", g - gasleft());
        hv.roll(_buyerEnd());
        Rule8Store.UnitItem[] memory items = _items(ns);
        g = gasleft();
        r8.releaseUnit(sellerId, 0, 0, items);
        _log(N == 8 ? "rule 8: releaseUnit (unit of 8) gas" : "rule 8: releaseUnit (unit of 32) gas", g - gasleft());
        g = gasleft();
        r8.passEpoch(sellerId);
        _log(N == 8 ? "rule 8: passEpoch (batch of 8) gas" : "rule 8: passEpoch (batch of 32) gas", g - gasleft());
        g = gasleft();
        _proveBinding(ns[0], x);
        _log("rule 8: proveBinding (one sale, only when it is needed) gas", g - gasleft());
    }

    /// The same epoch with 32 purchases and a unit of 32, for the slope per
    /// purchase.
    function test_gas_rule8Epoch32() public {
        N = 32;
        test_gas_rule8Epoch();
    }

    function test_gas_rule8SignedAnchorWithoutSignatures() public {
        _deployGas();
        bytes32[] memory ns = _buyN();
        _xTree(ns);
        hv.roll(600);
        Rule8Store.AnchorContent memory c = _content(0, uint32(N));
        bytes memory sig = _signContent(c);
        FairBindMerkle.ReceiptEntry[] memory list = _xEntries();
        uint256 g = gasleft();
        r8.anchorSigned(c, list, sig);
        _log("rule 8: anchorSigned (8 entries, no buyer signatures) gas", g - gasleft());
    }

    /// The first block after the buyer windows of epoch 0 (signing account:
    /// the claim window, epoch end 300 + 60 + 1,800).
    function _buyerEnd() internal pure returns (uint256) {
        return 300 + 60 + 1_800 + 1;
    }
}
