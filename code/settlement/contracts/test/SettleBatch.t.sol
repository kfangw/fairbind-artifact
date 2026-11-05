// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { SettleBatchBase, StateVm } from "./SettleBatchBase.sol";
// Keeps the mutation artifacts built when a filter selects only some tests.
import { RevertAllSettlement } from "./SettleBatchMutants.sol";

interface BurnTarget {
    function purchaseByKey(bytes32 keyId) external view returns (bytes32);
}

/// Burns all the gas it gets while the purchase of `key` is being settled
/// (its key is recorded before the token transfer): a payer that spends the
/// gas of its own item.
contract GasBurner {
    BurnTarget internal immutable target;
    bytes32 internal immutable key;

    constructor(address target_, bytes32 key_) {
        target = BurnTarget(target_);
        key = key_;
    }

    fallback() external {
        if (target.purchaseByKey(key) == bytes32(0)) return;
        while (true) { }
    }
}

/// Settlement batch (rule D2-34, 8.2 row 26): mixed sellers, a failed item
/// skipped with no state, the same key twice, bucket exhaustion on one
/// account, a payer that spends its gas, the remaining-gas check, the
/// self-call entry, and the equivalence of a batch with separate settle
/// calls in the same block (fuzzed, 200 runs).
contract SettleBatchTest is SettleBatchBase {
    function _start(uint256 capacity) internal {
        _deployBatch(ExchangeStore.MODE_VOTE_SIG, capacity, 3);
        _fundBuyers(0, 8);
    }

    function _three(FairBindCore.SettleItem memory a, FairBindCore.SettleItem memory b, FairBindCore.SettleItem memory c)
        internal
        pure
        returns (FairBindCore.SettleItem[] memory items)
    {
        items = new FairBindCore.SettleItem[](3);
        items[0] = a;
        items[1] = b;
        items[2] = c;
    }

    function _settled(FairBindCore.SettleItem memory it) internal view returns (bool) {
        return fairbind.getPurchase(it.authorization.nonce).settledBlock != 0;
    }

    /// Runs [ok, bad, ok] and returns whether the outer items settled, the
    /// middle one left no purchase and no key, and its skip reason.
    function _middleSkipped(FairBindCore.SettleItem memory bad) internal returns (bool clean, bytes4 reason) {
        FairBindCore.SettleItem memory a = _item(0, 0, VALUE);
        FairBindCore.SettleItem memory c = _item(1, 1, VALUE);
        bytes32 key = _keyOf(bad);
        bytes32 keyBefore = fairbind.purchaseByKey(key);
        uint256 countBefore = fairbind.getPurchase(bad.authorization.nonce).settledBlock;
        stv.recordLogs();
        uint256 settled = sb.settleBatch(_three(a, bad, c));
        (uint256[] memory idx, bytes4[] memory why) = _skips(stv.getRecordedLogs());
        clean = settled == 2 && _settled(a) && _settled(c) && fairbind.purchaseByKey(key) == keyBefore
            && fairbind.getPurchase(bad.authorization.nonce).settledBlock == countBefore && idx.length == 1 && idx[0] == 1;
        reason = why.length == 1 ? why[0] : bytes4(0);
    }

    function test_batchSettlesMixedSellers() public {
        _start(20);
        FairBindCore.SettleItem[] memory items = _three(_item(0, 0, VALUE), _item(1, 1, VALUE), _item(2, 2, 7_000));
        uint256 before_ = token.balanceOf(address(fairbind));
        require(sb.settleBatch(items) == 3, "three settled");
        for (uint256 i; i < 3; i++) {
            FairBindCore.PurchaseView memory p = fairbind.getPurchase(items[i].authorization.nonce);
            require(p.settledBlock == _now() && p.sellerId == sellerIds[i] && p.value == items[i].authorization.value, "record");
        }
        require(token.balanceOf(address(fairbind)) == before_ + 27_000, "paid");
    }

    /// (S2) A wrong authorization signature: the item is skipped with no
    /// state and the others settle.
    function test_failedItemIsSkipped() public {
        _start(20);
        FairBindCore.SettleItem memory bad = _itemWith(2, 2, VALUE, _ts() + 1000, _buyerKey(5));
        (bool clean, bytes4 reason) = _middleSkipped(bad);
        require(clean, "only the failed item is left out");
        require(reason == FairBindCore.TransferFailed.selector, "token refusal");
    }

    /// (S2) A skipped item can settle later: a buyer short of balance is
    /// funded and the same authorization settles on its own.
    function test_skippedItemSettlesLater() public {
        require(_retryAfterSkip(), "the same authorization settles later");
    }

    function test_skippedItemKeepingItsKeyIsCaught() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:KeepsKeySettlement";
        require(!_retryAfterSkip(), "mutation caught");
    }

    function _retryAfterSkip() internal returns (bool) {
        _start(20);
        FairBindCore.SettleItem memory bad = _item(2, 20, VALUE);
        (bool clean, bytes4 reason) = _middleSkipped(bad);
        require(reason == FairBindCore.TransferFailed.selector, "balance short");
        token.mint(bad.authorization.from, VALUE);
        (bool ok,) = address(fairbind).call(_settleCall(bad));
        return clean && ok && _settled(bad);
    }

    /// (S2) Each failure kind of 8.2 row 26 leaves only its item out.
    function test_eachFailureKindIsSkipped() public {
        _start(20);
        bytes4[7] memory want = [
            FairBindCore.ValueTooLarge.selector,
            FairBindCore.ValueTooLarge.selector,
            FairBindCore.KeyAlreadyUsed.selector,
            FairBindCore.AuthorizationExpired.selector,
            FairBindCore.TransferFailed.selector,
            FairBindCore.BondNotActive.selector,
            FairBindCore.ClaimsMismatch.selector
        ];
        for (uint256 k; k < 7; k++) {
            uint256 snap = sw.snapshotState();
            FairBindCore.SettleItem memory bad;
            if (k == 0) bad = _item(2, 2, 0);
            if (k == 1) bad = _item(2, 2, VALUE + 1);
            if (k == 2) {
                bad = _item(2, 2, VALUE);
                (bool ok,) = address(fairbind).call(_settleCall(bad));
                require(ok, "settled before");
            }
            if (k == 3) {
                bad = _itemWith(2, 2, VALUE, _ts() + 10, _buyerKey(2));
                xv.warp(_ts() + 10);
            }
            if (k == 4) bad = _item(2, 21, VALUE);
            if (k == 5) {
                bad = _item(2, 2, VALUE);
                uint32 bondId = fairbind.getSeller(sellerIds[2]).bondId;
                hv.prank(address(uint160(0x5E11E7 + 2)));
                fairbind.requestBondExit(bondId);
            }
            if (k == 6) {
                bad = _item(2, 2, VALUE);
                bad.claimsHash = keccak256("other claims");
            }
            (bool clean, bytes4 reason) = _middleSkipped(bad);
            require(clean, "only the failed item is left out");
            require(reason == want[k], "reason");
            sw.revertToState(snap);
        }
    }

    /// The same item twice: the second is skipped by the key check.
    function test_sameKeyTwiceSkipsTheSecond() public {
        require(_sameKeyReason() == FairBindCore.KeyAlreadyUsed.selector, "the key check skips the second");
    }

    function test_sameKeyWithoutTheKeyCheckIsCaught() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:NoKeyCheckSettlement";
        require(_sameKeyReason() != FairBindCore.KeyAlreadyUsed.selector, "mutation caught");
    }

    function _sameKeyReason() internal returns (bytes4) {
        _start(20);
        FairBindCore.SettleItem memory a = _item(0, 0, VALUE);
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](2);
        items[0] = a;
        items[1] = a;
        uint256 paid = token.balanceOf(a.authorization.from);
        stv.recordLogs();
        require(sb.settleBatch(items) == 1, "one settled");
        (uint256[] memory idx, bytes4[] memory why) = _skips(stv.getRecordedLogs());
        require(idx.length == 1 && idx[0] == 1, "the second skipped");
        require(token.balanceOf(a.authorization.from) == paid - VALUE, "paid once");
        return why[0];
    }

    /// A bucket that runs out skips the later items of its account only.
    function test_bucketExhaustionSkipsOnlyItsAccount() public {
        _start(2);
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](4);
        items[0] = _item(0, 0, VALUE);
        items[1] = _item(0, 1, VALUE);
        items[2] = _item(0, 2, VALUE);
        items[3] = _item(1, 3, VALUE);
        stv.recordLogs();
        require(sb.settleBatch(items) == 3, "three settled");
        (uint256[] memory idx, bytes4[] memory why) = _skips(stv.getRecordedLogs());
        require(idx.length == 1 && idx[0] == 2 && why[0] == FairBindCore.RateLimitExceeded.selector, "the third skipped");
        require(_settled(items[3]), "the other account settles");
    }

    /// A payer whose transfer spends all its gas is skipped within the item
    /// gas, and the later items settle.
    function test_gasSpendingPayerCannotBlockTheOthers() public {
        _start(20);
        FairBindCore.SettleItem[] memory items = _three(_item(0, 0, VALUE), _item(1, 1, VALUE), _item(2, 2, VALUE));
        GasBurner burner = new GasBurner(address(fairbind), _keyOf(items[0]));
        token.setCallback(address(burner), "");
        stv.recordLogs();
        uint256 g = gasleft();
        require(sb.settleBatch{ gas: 5_000_000 }(items) == 2, "two settled");
        g -= gasleft();
        (uint256[] memory idx,) = _skips(stv.getRecordedLogs());
        require(idx.length == 1 && idx[0] == 0, "the spending item skipped");
        require(_settled(items[1]) && _settled(items[2]), "later items settle");
        _log("batch of three with a gas-spending payer, gas", g);
    }

    /// Less gas left than one item may take reverts the whole batch.
    function test_gasShortRevertsTheBatch() public {
        require(_gasShortReverts(), "reverted as a whole");
    }

    function test_gasShortWithoutTheCheckIsCaught() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:NoGasCheckSettlement";
        require(!_gasShortReverts(), "mutation caught");
    }

    function _gasShortReverts() internal returns (bool) {
        _start(20);
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](2);
        items[0] = _item(0, 0, VALUE);
        items[1] = _item(1, 1, VALUE);
        (bool ok, bytes memory ret) = address(fairbind).call{ gas: 800_000 }(_batchCall(items));
        if (ok) return false;
        require(!_settled(items[0]), "nothing kept");
        return ret.length == 4 && bytes4(ret) == FairBindCore.BatchGasShort.selector;
    }

    /// A failed item reverts nothing else.
    function test_failureRevertingTheBatchIsCaught() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:RevertAllSettlement";
        _start(20);
        FairBindCore.SettleItem[] memory items = _three(_item(0, 0, VALUE), _item(1, 1, 0), _item(2, 2, VALUE));
        (bool ok,) = address(fairbind).call(_batchCall(items));
        require(!ok, "mutation caught");
    }

    /// A settle call made from inside an item (here by the token during the
    /// transfer) does not run inside the batch's lock.
    function test_settleFromInsideAnItemIsRefused() public {
        _start(20);
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](1);
        items[0] = _item(0, 0, VALUE);
        FairBindCore.SettleItem memory other = _item(1, 1, VALUE);
        token.setCallback(address(fairbind), _settleCall(other));
        require(sb.settleBatch(items) == 1, "the item settles");
        require(!token.callbackSuccess(), "inner settle refused");
        require(token.callbackError() == FairBindCore.InvalidConfiguration.selector, "by the lock");
        require(!_settled(other), "nothing settled inside");
    }

    // ------------------------------------------------------- equivalence

    /// Items of a random batch: 1 to 12 items over three sellers and nine
    /// buyers (buyer 8 has no balance), with zero values, values over the
    /// cap, repeated items, wrong signatures and expired authorizations
    /// mixed in; a bucket of 4 units per account.
    function _randomItems(uint256 seed) internal returns (FairBindCore.SettleItem[] memory items) {
        uint256 n = 1 + seed % 12;
        items = new FairBindCore.SettleItem[](n);
        for (uint256 i; i < n; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            uint256 s = r % 3;
            uint256 b = (r >> 8) % 9;
            uint256 kind = (r >> 16) % 12;
            if (kind == 7 && i != 0) items[i] = items[(r >> 24) % i];
            else if (kind == 8) items[i] = _itemWith(s, b, VALUE, _ts() + 1000, _buyerKey(b + 1));
            else if (kind == 9) items[i] = _itemWith(s, b, VALUE, _ts(), _buyerKey(b));
            else if (kind == 10) items[i] = _item(s, b, 0);
            else if (kind == 11) items[i] = _item(s, b, VALUE + 1 + (r >> 32) % 100);
            else items[i] = _item(s, b, 1 + (r >> 32) % VALUE);
        }
    }

    function _startRandom(uint256 seed) internal {
        _deployBatch(seed & 1 == 0 ? ExchangeStore.MODE_VOTE_SIG : ExchangeStore.MODE_PROOF, 4, 3);
        _fundBuyers(0, 8);
    }

    /// (S3)
    /// forge-config: default.fuzz.runs = 200
    function testFuzz_batchEqualsSeparateSettles(uint256 seed) public {
        _startRandom(seed);
        require(_equivalent(_randomItems(seed)), "same state and events");
    }

    /// A build whose failed items keep their key differs from the separate
    /// settle calls.
    function test_equivalenceCatchesAKeptKey() public {
        moduleNames[SETTLEMENT] = "SettleBatchMutants.sol:KeepsKeySettlement";
        _start(20);
        FairBindCore.SettleItem[] memory items = _three(_item(0, 0, VALUE), _item(1, 1, 0), _item(2, 2, VALUE));
        require(!_equivalent(items), "mutation caught");
    }

    /// One settle and a batch of that one item leave the same state.
    function test_oneItemBatchEqualsSettle() public {
        _start(20);
        FairBindCore.SettleItem[] memory items = new FairBindCore.SettleItem[](1);
        items[0] = _item(0, 0, VALUE);
        require(_equivalent(items), "same state");
    }
}
