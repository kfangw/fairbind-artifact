// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { SettleBatchBase, StateVm } from "./SettleBatchBase.sol";
import { MultiCall } from "./ExchangeMocks.sol";
// Keeps the mutation artifacts built when a filter selects only some tests.
import { NoMarkSettlement } from "./SettleBatchMutants.sol";

/// The transient cost mark of settle and settleBatch (8.2 row 27): a key
/// dispute PASS proof called after a settlement in the same transaction
/// leaves out the fixed share of the transaction. Run with --isolate, so
/// that each call of the test is a transaction of its own.
contract SettleBatchCostTest is SettleBatchBase {
    bytes32 internal constant ENDED = keccak256("ProofDisputeEnded(bytes32,bool,uint256,uint256)");
    uint32 internal constant BIG_ENV = 12_000;
    uint256 internal constant BIG_SHARE = 6_000;

    function _cost() internal returns (uint256 c) {
        StateVm.Log[] memory logs = stv.getRecordedLogs();
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].topics.length == 0 || logs[i].topics[0] != ENDED) continue;
            (,, c) = abi.decode(logs[i].data, (bool, uint256, uint256));
        }
    }

    function _proveCall(bytes32 n) internal view returns (bytes memory) {
        return abi.encodeWithSelector(fx.prove.selector, n, uint8(0), _passProof(n));
    }

    /// The measured cost of a key dispute's proof alone and after a
    /// settlement (`batch`: a one-item settleBatch) in one transaction.
    function _proofAfterSettlement(bool batch) internal returns (uint256 alone, uint256 after_) {
        envBytes = BIG_ENV;
        _deployBatch(ExchangeStore.MODE_PROOF, 20, 1);
        _fundBuyers(0, 2);
        bytes32 a = _buy();
        _postSigned(a);
        hv.prank(buyer);
        fx.openProofDispute(a, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](1);
        items[0] = _item(0, 1, VALUE);
        uint256 snap = sw.snapshotState();
        stv.recordLogs();
        (bool ok,) = address(fairbind).call(_proveCall(a));
        require(ok, "proof alone");
        alone = _cost();
        sw.revertToState(snap);
        bytes[] memory calls = new bytes[](2);
        calls[0] = batch ? _batchCall(items) : _settleCall(items[0]);
        calls[1] = _proveCall(a);
        MultiCall m = new MultiCall();
        stv.recordLogs();
        m.run(address(fairbind), calls);
        after_ = _cost();
        require(fairbind.getPurchase(items[0].authorization.nonce).settledBlock != 0, "settled");
        _log("proof alone", alone);
        _log("proof after the settlement", after_);
    }

    function test_proofAfterSettleTakesNoFixedShare() public {
        (uint256 alone, uint256 after_) = _proofAfterSettlement(false);
        require(alone > after_ + BIG_SHARE, "no fixed share after settle");
    }

    function test_proofAfterSettleBatchTakesNoFixedShare() public {
        (uint256 alone, uint256 after_) = _proofAfterSettlement(true);
        require(alone > after_ + BIG_SHARE, "no fixed share after settleBatch");
    }

    function test_settlementWithoutTheMarkIsCaught() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:NoMarkSettlement";
        (uint256 alone, uint256 after_) = _proofAfterSettlement(true);
        require(alone < after_ + BIG_SHARE, "mutation caught");
    }
}
