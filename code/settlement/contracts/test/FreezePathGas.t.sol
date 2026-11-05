// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

interface FreezeGasVm {
    function getBlockNumber() external view returns (uint256);
}

/// Call-frame gas of the freeze path: the confirmed failure that freezes
/// (timeoutServe of an UNSERVED dispute), a second failure in the open claim
/// window, a frozen-pool claim, the forfeiture of the window, and the release
/// of an entry settled before the failing sale. It uses only calls that exist
/// before ADR 0030, so the same file measures both builds. Run with
/// --isolate. Every number is logged; nothing is asserted about gas.
contract FreezePathGasTest is ReproBase {
    FreezeGasVm internal constant fv = FreezeGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant G = 10_000;

    function _now() internal view returns (uint256) {
        return fv.getBlockNumber();
    }

    function _dispute(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
    }

    /// The failing sale is the account's first: the window holds every entry.
    function test_gas_freezeFirstSale() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32 d = _purchase(G);
        hv.roll(20);
        _purchase(G);
        hv.roll(81);
        _dispute(d);
        hv.roll(382);
        uint256 g = gasleft();
        fairbind.timeoutServe(d);
        _log("timeoutServe, first failure (freeze) gas", g - gasleft());
        fairbind.claimRefund(d);
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(uint256(fairbind.getBond(bondId).claimUntilBlock) + 1);
        g = gasleft();
        fairbind.forfeitUnclaimed(bondId);
        _log("forfeitUnclaimed, failing sale first, gas", g - gasleft());
    }

    /// An entry e settled before the failing sale d and one l after it.
    function test_gas_freezeLaterSale() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32 e = _purchase(G);
        hv.roll(20);
        bytes32 d = _purchase(G);
        hv.roll(30);
        bytes32 l = _purchase(G);
        hv.roll(81);
        _dispute(e);
        _dispute(d);
        hv.roll(382);
        uint256 g = gasleft();
        fairbind.timeoutServe(d);
        _log("timeoutServe, first failure (freeze) gas", g - gasleft());
        hv.roll(383);
        g = gasleft();
        fairbind.timeoutServe(e);
        _log("timeoutServe, second failure in the claim window gas", g - gasleft());
        fairbind.claimRefund(d);
        fairbind.claimRefund(e);
        FairBindCore.FairBindReceipt memory r = _receipt(l);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory none = FairBindCore.ReceiptProof(0, 0, new bytes32[](0));
        g = gasleft();
        fairbind.claimRefund(l, r, sig, none);
        _log("claimRefund from the frozen pool gas", g - gasleft());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(uint256(fairbind.getBond(bondId).claimUntilBlock) + 1);
        g = gasleft();
        fairbind.forfeitUnclaimed(bondId);
        _log("forfeitUnclaimed, after a lowered start, gas", g - gasleft());
    }
}
