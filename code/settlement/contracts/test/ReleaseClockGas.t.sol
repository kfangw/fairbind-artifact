// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { Impl1bBase } from "./Design2Impl1b.t.sol";

interface GasBlockVm {
    function getBlockNumber() external view returns (uint256);
}

/// Call-frame gas of the calls that ADR 0029 touches: settle, anchor, seal,
/// an openSample whose search is exhausted (a case that starts to wait), the
/// same while another case of the account already waits, a redraw that
/// assigns (a case that stops waiting), and releasePurchase without and with
/// pauses of the account since the entry's settlement. The test uses only
/// calls that exist before ADR 0029, so the same file measures both builds.
/// Every number is logged; nothing is asserted about gas.
contract ReleaseClockGasTest is Impl1bBase {
    GasBlockVm internal constant gv = GasBlockVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function _now() internal view returns (uint256) {
        return gv.getBlockNumber();
    }

    /// Half of all purchases sampled; verifiers open with 10% exposure, so no
    /// verifier of the first checkpoint has room for one case (ADR 0028 test
    /// fixture) and every initial search of the epoch waits.
    function _profileHalf() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _sampledProfile(20);
        p.samplePpm = 500_000;
        p.verifierExposurePpm = 100_000;
    }

    function test_gas_releaseClockPaths() public {
        _deploy(_profileHalf());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](8);
        uint256 g = gasleft();
        ns[0] = _purchase(G);
        _log("settle (first of the account) gas", g - gasleft());
        g = gasleft();
        ns[1] = _purchase(G);
        _log("settle (second) gas", g - gasleft());
        for (uint256 i = 2; i < ns.length; i++) ns[i] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        FairBindMerkle.ReceiptEntry[] memory list = _treeEntries();
        g = gasleft();
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, list, uint32(ns.length), keccak256("publication"));
        _log("anchor (8 entries) gas", g - gasleft());
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, BEACON);
        g = gasleft();
        fairbind.seal(sellerId, 0);
        _log("seal gas", g - gasleft());

        bytes32[] memory sampled = new bytes32[](8);
        bytes32[] memory plain = new bytes32[](8);
        uint256 s;
        uint256 u;
        for (uint256 i; i < ns.length; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            if (eligible) sampled[s++] = ns[i];
            else plain[u++] = ns[i];
        }
        require(s >= 2 && u >= 2, "fixture: two sampled and two unsampled purchases");

        g = gasleft();
        fairbind.openSample(sampled[0]);
        _log("openSample, first case of the account to wait, gas", g - gasleft());
        require(fairbind.getCase(sampled[0]).state == uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT), "waits");
        hv.roll(_now() + 10);
        g = gasleft();
        fairbind.openSample(sampled[1]);
        _log("openSample, second waiting case, gas", g - gasleft());

        // A newer checkpoint with room for every verifier, and its redraw value.
        for (uint32 id = 1; id <= 14; id++) fairbind.topUpVerifierBond(id, 10_000_000);
        hv.roll(_now() + 1);
        fairbind.checkpointVerifierTree(PROFILE);
        uint256 rb = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
        hv.roll(rb + 1);
        hv.setBlockhash(rb, keccak256("redraw"));
        g = gasleft();
        fairbind.assignVerifier(sampled[0]);
        _log("assignVerifier redraw, another case still waits, gas", g - gasleft());
        hv.roll(_now() + 10);
        g = gasleft();
        fairbind.assignVerifier(sampled[1]);
        _log("assignVerifier redraw, last waiting case, gas", g - gasleft());
        require(fairbind.getCase(sampled[1]).state == uint8(FairBindCore.CaseState.JUDGING), "assigned");

        // Release after every condition, including the paused blocks.
        hv.roll(200_000);
        g = gasleft();
        fairbind.releasePurchase(plain[0]);
        _log("releasePurchase, one pause since settlement, gas", g - gasleft());
        g = gasleft();
        fairbind.releasePurchase(plain[1]);
        _log("releasePurchase, one pause since settlement (warm), gas", g - gasleft());
    }

    /// The same release on an account that never waited.
    function test_gas_releaseWithoutPause() public {
        FairBindCore.ServiceProfileInput memory p = _profileHalf();
        p.verifierExposurePpm = 500_000;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](8);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        bytes32 plain;
        for (uint256 i; i < ns.length && plain == 0; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            if (!eligible) plain = ns[i];
        }
        require(plain != 0, "fixture: an unsampled purchase");
        hv.roll(200_000);
        uint256 g = gasleft();
        fairbind.releasePurchase(plain);
        _log("releasePurchase, account never paused, gas", g - gasleft());
    }
}
