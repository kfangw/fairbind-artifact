// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";

/// ADR 0028 under batch terms (ADR 0032): a first-stage sample case whose
/// every round names a verifier that left by its own action waits for the
/// next checkpoint; its redraw, with the AUX value of its registered use,
/// places it in its candidate's queue like any other case, keeping its batch
/// and rank.
contract BatchWaitTest is BatchBase {
    uint8 internal constant WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);
    uint8 internal constant QUEUED = uint8(FairBindCore.CaseState.QUEUED);
    uint8 internal constant JUDGING = uint8(FairBindCore.CaseState.JUDGING);

    function _redrawId(bytes32 n, uint32 redraw, uint64 t) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(VRF_AUX, abi.encode(keccak256("FairBind/redraw/v1"), n, uint8(1), redraw, t))
        );
    }

    /// Three sample cases of batch 0. All fourteen verifiers of the
    /// checkpoint of A_0 ask to exit at 1100, before the batch value is
    /// stored at 1113, so every round of every case is skipped and the cases
    /// wait. Fourteen new verifiers register at 1100: one with 100 USDC (one
    /// slot at slotValue 30 USDC), thirteen at the 1 USDC minimum (no slot).
    function _waiting() internal returns (bytes32[] memory ns) {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        _deployBatched(_batchProfile(), t, _equalBonds());
        hv.roll(10);
        ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1100);
        for (uint32 u = 1; u <= 14; u++) fairbind.requestVerifierExit(u);
        for (uint32 i = 15; i <= 28; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), i == 15 ? 100_000_000 : 1_000_000);
        }
        _assignBatch(0);
        for (uint256 i; i < 3; i++) require(_state(ns[i]) == WAITING, "every round left by its own action");
    }

    /// The redraw of each case on the checkpoint of A_2 (the first written
    /// after the search) draws from its own AUX value and goes to round 0's
    /// candidate; a candidate already judging keeps it queued in key order,
    /// paused, with its batch, rank and key unchanged.
    function test_waitingCaseRedrawsIntoAQueue() public {
        bytes32[] memory ns = _waiting();
        uint32 bondId = _bondOfSeller(sellerId);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == 3, "three waiting cases pause");
        uint256[] memory keys = new uint256[](3);
        for (uint256 i; i < 3; i++) keys[i] = fb.getBatchEntry(ns[i]).key;
        hv.roll(1301);
        hv.prank(KEEPER);
        uint64 version = fb.checkpointAt(PROFILE, 2);
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            fairbind.registerRedraw(ns[i]);
        }
        hv.roll(1302);
        bytes32[] memory values = new bytes32[](3);
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            fairbind.requestRedrawValue(ns[i]);
            values[i] = _fulfill(_redrawId(ns[i], 1, 1301));
        }
        uint256 queued;
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            fairbind.assignVerifier(ns[i]);
            uint32 u = _candidate(version, values[i], ns[i], 1, 0, 0);
            require(u > 14, "a new verifier");
            BatchStore.Entry memory en = fb.getBatchEntry(ns[i]);
            uint8 st = _state(ns[i]);
            if (st == QUEUED) {
                queued++;
                require(en.verifier == u, "queued at round 0's candidate");
            } else {
                require(st == JUDGING && fairbind.getCase(ns[i]).assignedVerifierId == u, "started at round 0's candidate");
            }
            require(en.batch == 0 && en.key == keys[i], "batch and key kept");
        }
        require(queued != 0, "a redrawn case waits in a queue");
        (waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == queued, "queued redrawn cases pause");
        for (uint32 v = 15; v <= 28; v++) {
            bytes32[] memory q = fb.getQueue(v);
            for (uint256 i = 1; i < q.length; i++) {
                require(fb.getBatchEntry(q[i - 1]).key < fb.getBatchEntry(q[i]).key, "key order");
            }
        }
    }
}
