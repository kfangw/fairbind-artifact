// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MultiCall, MockUniquePriceFeed } from "./ExchangeMocks.sol";

interface LogVm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }

    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

/// The measured cost of a key dispute's PASS proof (ADR 0037, rule D2-33
/// (e') 1 2): the fixed share of a transaction counts once, priority fees
/// never count, and the L1 share is the oracle's bound of the call data
/// length plus bEnv (less the bound of bEnv for a later call). Run with --isolate, so that each call of the test is a
/// transaction of its own and the transient mark starts clear.
contract ExchangeCostTest is ExchangeBase {
    LogVm internal constant lv = LogVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant ENDED = keccak256("ProofDisputeEnded(bytes32,bool,uint256,uint256)");
    /// An isolated call runs with a zero base fee in this test runner, so
    /// the fixed share shows through its L1 part: the bound of an envelope
    /// of 12,000 bytes is 6,467 token units at the test prices.
    uint32 internal constant BIG_ENV = 12_000;
    uint256 internal constant BIG_SHARE = 6_000;

    function _startCost() internal {
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        ExchangeStore.Input memory x = _input(ExchangeStore.MODE_PROOF);
        x.bEnv = BIG_ENV;
        _deployExchange(_exchangeProfile(), x, true);
        hv.roll(10);
    }

    function _disputed() internal returns (bytes32 n) {
        n = _buy();
        _postSigned(n);
        hv.prank(buyer);
        fx.openProofDispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
    }

    function _costs() internal returns (uint256[] memory out) {
        LogVm.Log[] memory logs = lv.getRecordedLogs();
        uint256 k;
        for (uint256 i; i < logs.length; i++) if (logs[i].topics.length != 0 && logs[i].topics[0] == ENDED) k++;
        out = new uint256[](k);
        k = 0;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].topics.length == 0 || logs[i].topics[0] != ENDED) continue;
            (,, uint256 cost) = abi.decode(logs[i].data, (bool, uint256, uint256));
            out[k++] = cost;
        }
    }

    function _proveCall(bytes32 n) internal view returns (bytes memory) {
        return abi.encodeWithSelector(fx.prove.selector, n, uint8(0), _passProof(n));
    }

    /// Two key-dispute proofs in one transaction: the second leaves out the
    /// fixed share the first counted.
    function _gapInOneTransaction(string memory pass) internal returns (uint256 first, uint256 second) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _startCost();
        bytes32 a = _disputed();
        bytes32 b = _disputed();
        MultiCall m = new MultiCall();
        bytes[] memory calls = new bytes[](2);
        calls[0] = _proveCall(a);
        calls[1] = _proveCall(b);
        lv.recordLogs();
        m.run(address(fairbind), calls);
        uint256[] memory c = _costs();
        require(c.length == 2, "two disputes ended");
        _log("first cost", c[0]);
        _log("second cost", c[1]);
        return (c[0], c[1]);
    }

    function test_fixedShareCountsOncePerTransaction() public {
        (uint256 first, uint256 second) = _gapInOneTransaction("");
        require(first > second + BIG_SHARE, "the second call leaves the fixed share out");
    }

    function test_fixedShareOnEveryCallIsCaught() public {
        (uint256 first, uint256 second) = _gapInOneTransaction("ExchangeMutants.sol:EveryCallFixedProof");
        require(first < second + BIG_SHARE, "mutation caught");
    }

    /// The L1 share of each proof, from the length of its call data: with a
    /// zero base fee the measured cost is pi * L1 share / 1e18.
    function _boundShares(string memory pass) internal returns (bool exact) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _startCost();
        bytes32 a = _disputed();
        bytes32 b = _disputed();
        uint256 la = _proveCall(a).length;
        uint256 lb = _proveCall(b).length;
        MultiCall m = new MultiCall();
        bytes[] memory calls = new bytes[](2);
        calls[0] = _proveCall(a);
        calls[1] = _proveCall(b);
        lv.recordLogs();
        m.run(address(fairbind), calls);
        uint256[] memory c = _costs();
        uint256 pi = _input(ExchangeStore.MODE_PROOF).priceCap;
        uint256 first = oracle.getL1FeeUpperBound(la + BIG_ENV);
        uint256 second = oracle.getL1FeeUpperBound(lb + BIG_ENV) - oracle.getL1FeeUpperBound(BIG_ENV);
        _log("call data bytes", la);
        _log("first cost", c[0]);
        _log("first, from the bound", first * pi / 1e18);
        _log("second cost", c[1]);
        _log("second, from the bound", second * pi / 1e18);
        return c[0] == first * pi / 1e18 && c[1] == second * pi / 1e18;
    }

    function test_keyDisputeL1ShareIsTheBoundOfItsLength() public {
        require(_boundShares(""), "the bound of the length");
    }

    function test_keyDisputeL1ShareByContentIsCaught() public {
        require(!_boundShares("ExchangeMutants.sol:GetL1FeeProof"), "mutation caught");
    }

    /// A posting earlier in the transaction counted the fixed share.
    function test_proofAfterAPostingInItsTransactionTakesNoFixedShare() public {
        _startCost();
        bytes32 a = _disputed();
        bytes32 b = _buy();
        Bundle memory bb = _bundle(b);
        ExchangeStore.Post memory q = _post(b, bb, BUYER_KEY);
        bytes memory postCall = abi.encodeWithSelector(fx.postReceipt.selector, q, _sig(SELLER_KEY, fx.postDigest(q)));
        uint256 snap = sw.snapshotState();
        lv.recordLogs();
        CallExt.call(address(fairbind), _proveCall(a));
        uint256 alone = _costs()[0];
        sw.revertToState(snap);
        MultiCall m = new MultiCall();
        bytes[] memory calls = new bytes[](2);
        calls[0] = postCall;
        calls[1] = _proveCall(a);
        lv.recordLogs();
        m.run(address(fairbind), calls);
        uint256 after_ = _costs()[0];
        _log("alone", alone);
        _log("after posting", after_);
        require(alone > after_ + BIG_SHARE, "no fixed share after the posting");
    }
}

library CallExt {
    function call(address target, bytes memory data) internal {
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }
}
