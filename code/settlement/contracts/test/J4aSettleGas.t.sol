// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { D2CheckBase } from "./review/D2ContractCheck.t.sol";

interface J3bVm {
    function load(address target, bytes32 slot) external view returns (bytes32);
}

/// Call-frame gas (gasleft deltas of the external call, including the
/// calldata decoding of the router and the delegatecall into the module) of
/// the settlement path of one account (journal J4a): settle, anchor, seal,
/// openSample, submitSampleReceipt, judge, finalizeCase, releasePurchase.
/// Run: forge test --match-contract J4aSettleGasTest -vv
/// Every number is logged as "J4a <name> <gas>"; nothing is asserted about
/// gas, so the same file measures the build before and after a change. The
/// mock token (EIP-3009 with signature check) costs what the mock costs, not
/// what a deployed USDC costs.
contract J4aSettleGasTest is D2CheckBase {
    function _gas(string memory name, uint256 g) internal view {
        _log(string.concat("J4a ", name), g);
    }

    /// Account without design 2 terms: constant samplePpm = PPM.
    function test_gas_settlementPath_untiered() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        _walk("untiered");
    }

    /// Account with a tier and value caps (rules D2-2, D2-5): settle also
    /// reads the tier terms and writes settledSamplePpm.
    function test_gas_settlementPath_tiered() public {
        _deployD2(_profileD2(), true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        _walk("tiered");
    }

    /// settle no longer stores the claims hash or a used-nonce flag per purchase;
    /// the purchase view and the replay checks behave as before.
    function test_purchaseViewAndReplayChecksAreUnchanged() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        SettleArgs memory a = _settleArgs(G);
        _settle(a);
        FairBindCore.PurchaseView memory view_ = fairbind.getPurchase(a.nonce);
        require(view_.claimsHash == CLAIMS && view_.nonce == a.nonce && view_.sellerId == sellerId, "view");
        require(fairbind.getPurchase(bytes32(uint256(1))).claimsHash == bytes32(0), "unknown purchase is empty");
        hv.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        fairbind.settle(sellerId, PROFILE, CLAIMS, a.key, a.req, a.auth, a.sig);
    }

    /// settle no longer writes the nonce field of the purchase record (journal J3b):
    /// the record's first slot stays zero, getPurchase returns the key as the nonce,
    /// an unknown nonce reads as no purchase, and the same nonce cannot settle twice.
    function test_purchaseNonceFieldIsTheKey() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        SettleArgs memory a = _settleArgs(G);
        _settle(a);
        SettleArgs memory b = _settleArgs(G);
        _settle(b);
        FairBindCore.PurchaseView memory va = fairbind.getPurchase(a.nonce);
        FairBindCore.PurchaseView memory vb = fairbind.getPurchase(b.nonce);
        require(va.nonce == a.nonce && vb.nonce == b.nonce && va.nonce != vb.nonce, "nonce from key");
        require(va.settledBlock == 10 && va.requestHash == a.req && va.claimsHash == CLAIMS, "view");
        // The record of a.nonce: find the mapping slot by its requestHash (slot 4 of the
        // record), then check that slot 0, where the nonce field lives, was never written.
        J3bVm vm_ = J3bVm(address(uint160(uint256(keccak256("hevm cheat code")))));
        bool found;
        for (uint256 slot; slot < 512 && !found; slot++) {
            uint256 base = uint256(keccak256(abi.encode(a.nonce, slot)));
            if (vm_.load(address(fairbind), bytes32(base + 4)) == a.req) {
                found = true;
                require(vm_.load(address(fairbind), bytes32(base)) == bytes32(0), "nonce field written");
                require(vm_.load(address(fairbind), bytes32(base + 5)) == bytes32(0), "claimsHash written");
            }
        }
        require(found, "record slot");
        bytes32 unknown = keccak256("unknown purchase");
        FairBindCore.PurchaseView memory vu = fairbind.getPurchase(unknown);
        require(vu.nonce == bytes32(0) && vu.settledBlock == 0 && vu.claimsHash == bytes32(0), "unknown is empty");
        (bool eligible, bool known) = fairbind.isSampled(unknown);
        require(!eligible && !known, "unknown not sampled");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimEpochFailure(unknown);
        hv.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        fairbind.settle(sellerId, PROFILE, CLAIMS, a.key, a.req, a.auth, a.sig);
        hv.roll(11);
        hv.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        fairbind.settle(sellerId, PROFILE, CLAIMS, b.key, b.req, b.auth, b.sig);
    }

    function _walk(string memory tag) internal {
        uint256 value = bytes(tag)[0] == "t" ? CAP_LARGE : G;
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](4);
        uint256 g;
        for (uint256 i; i < 4; i++) {
            SettleArgs memory a = _settleArgs(value);
            g = gasleft();
            _settle(a);
            g -= gasleft();
            ns[i] = a.nonce;
            if (i == 0) _gas(string.concat(tag, " settle first of the account"), g);
            if (i == 1) _gas(string.concat(tag, " settle second"), g);
            if (i == 3) _gas(string.concat(tag, " settle fourth"), g);
        }
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        g = gasleft();
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
        _gas(string.concat(tag, " anchor 4 entries"), g - gasleft());
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        g = gasleft();
        fairbind.seal(sellerId, 0);
        _gas(string.concat(tag, " seal"), g - gasleft());
        g = gasleft();
        fairbind.openSample(ns[0]);
        _gas(string.concat(tag, " openSample"), g - gasleft());
        FairBindCore.FairBindReceipt memory r = _receipt(ns[0]);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory proof = _proof(ns[0]);
        g = gasleft();
        fairbind.submitSampleReceipt(ns[0], r, sig, proof);
        _gas(string.concat(tag, " submitSampleReceipt"), g - gasleft());
        FairBindCore.SignedVerdict memory v = _verdict(ns[0], uint8(FairBindCore.Verdict.PASS));
        bytes memory vsig = _sig(1000 + v.verifierId, fairbind.verdictDigest(v));
        bytes memory rsig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        g = gasleft();
        fairbind.judge(v, vsig, r, rsig, proof);
        _gas(string.concat(tag, " judge"), g - gasleft());
        uint64 rb = fairbind.getCase(ns[0]).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        g = gasleft();
        fairbind.finalizeCase(ns[0]);
        _gas(string.concat(tag, " finalizeCase"), g - gasleft());
        hv.roll(60_000);
        g = gasleft();
        fairbind.releasePurchase(ns[0]);
        _gas(string.concat(tag, " releasePurchase (sampled, judged)"), g - gasleft());
    }
}
