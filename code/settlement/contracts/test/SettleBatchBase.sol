// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";

interface ISettleBatch {
    function settleBatch(FairBindCore.SettleItem[] calldata items) external returns (uint256 settled);
}

interface StateVm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }

    function record() external;
    function accesses(address target) external returns (bytes32[] memory reads, bytes32[] memory writes);
    function load(address target, bytes32 slot) external view returns (bytes32);
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

/// Sellers, buyers and items for the settlement batch (rule D2-34): up to
/// 32 sellers, each with its own account, and buyers with their own keys.
abstract contract SettleBatchBase is ExchangeBase {
    StateVm internal constant stv = StateVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant SETTLED_TOPIC =
        keccak256("Settled(bytes32,bytes32,uint32,uint32,uint32,address,uint256,uint24,bytes32,bytes32)");
    bytes32 internal constant SKIPPED_TOPIC = keccak256("SettlementSkipped(uint256,bytes32,bytes4)");
    uint256 internal constant SELLER_KEY_BASE = 0x5E000;
    uint256 internal constant BUYER_KEY_BASE = 0xB0000;
    uint256 internal constant VALUE = 10_000;

    ISettleBatch internal sb;
    uint32[] internal sellerIds;
    uint128 internal itemKey = 1_000_000;
    /// bEnv of the deployment when not zero.
    uint32 internal envBytes;

    /// The profile of the batch tests: the exchange profile with a bucket
    /// of `capacity` units.
    function _deployBatch(uint8 m, uint256 capacity, uint256 sellers) internal {
        mode = m;
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.bucketCapacity = uint32(capacity);
        ExchangeStore.Input memory x = _input(mode);
        if (envBytes != 0) x.bEnv = envBytes;
        _deployExchange(p, x, true);
        sb = ISettleBatch(address(fairbind));
        sellerIds.push(sellerId);
        for (uint256 i = 1; i < sellers; i++) {
            address owner = address(uint160(0x5E11E7 + i));
            token.mint(owner, 1_000_000_000_000);
            hv.startPrank(owner);
            token.approve(address(fairbind), type(uint256).max);
            sellerIds.push(
                registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY_BASE + i), CLAIMS, uint128(p.sellerPenalty))
            );
            hv.stopPrank();
        }
        hv.roll(10);
    }

    function _buyerKey(uint256 i) internal pure returns (uint256) {
        return BUYER_KEY_BASE + i;
    }

    /// Mints to buyers [from, from + count).
    function _fundBuyers(uint256 from, uint256 count) internal {
        for (uint256 i = from; i < from + count; i++) token.mint(hv.addr(_buyerKey(i)), 1_000_000_000);
    }

    /// An item of buyer `b` paying `value` to seller index `s`.
    function _item(uint256 s, uint256 b, uint256 value) internal returns (FairBindCore.SettleItem memory) {
        return _itemWith(s, b, value, _ts() + 1000, _buyerKey(b));
    }

    /// An item with its validBefore and the key that signs its authorization.
    function _itemWith(uint256 s, uint256 b, uint256 value, uint256 before_, uint256 signKey)
        internal
        returns (FairBindCore.SettleItem memory it)
    {
        address from = hv.addr(_buyerKey(b));
        bytes16 k = bytes16(itemKey++);
        bytes32 req = keccak256(abi.encode("request", k));
        uint32 sid = sellerIds[s];
        bytes32 n = fairbind.deriveNonce(sid, PROFILE, CLAIMS, from, k, req);
        uint256 after_ = _ts() - 5;
        it.sellerId = sid;
        it.profileId = PROFILE;
        it.claimsHash = CLAIMS;
        it.idempotencyKey = k;
        it.requestHash = req;
        it.authorization = FairBindCore.TransferAuthorization(from, address(fairbind), value, after_, before_, n);
        it.paymentSignature =
            _sig(signKey, token.receiveAuthorizationDigest(from, address(fairbind), value, after_, before_, n));
    }

    function _keyOf(FairBindCore.SettleItem memory it) internal view returns (bytes32) {
        return fairbind.deriveKeyId(it.sellerId, it.authorization.from, it.idempotencyKey);
    }

    function _settleCall(FairBindCore.SettleItem memory it) internal view returns (bytes memory) {
        return abi.encodeCall(
            fairbind.settle,
            (it.sellerId, it.profileId, it.claimsHash, it.idempotencyKey, it.requestHash, it.authorization, it.paymentSignature)
        );
    }

    function _batchCall(FairBindCore.SettleItem[] memory items) internal pure returns (bytes memory) {
        return abi.encodeCall(ISettleBatch.settleBatch, (items));
    }

    /// Runs the items as separate settle calls in order; a reverted one leaves nothing.
    function _settleEach(FairBindCore.SettleItem[] memory items) internal returns (uint256 settled) {
        for (uint256 i; i < items.length; i++) {
            (bool ok,) = address(fairbind).call(_settleCall(items[i]));
            if (ok) settled++;
        }
    }

    function _settledCount(bytes32 n) internal view returns (bool) {
        return fairbind.getPurchase(n).settledBlock != 0;
    }

    /// Skip events of the recorded logs: (index, reason) pairs.
    function _skips(StateVm.Log[] memory logs) internal pure returns (uint256[] memory idx, bytes4[] memory why) {
        uint256 k;
        for (uint256 i; i < logs.length; i++) if (logs[i].topics.length != 0 && logs[i].topics[0] == SKIPPED_TOPIC) k++;
        idx = new uint256[](k);
        why = new bytes4[](k);
        k = 0;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].topics.length == 0 || logs[i].topics[0] != SKIPPED_TOPIC) continue;
            idx[k] = uint256(logs[i].topics[1]);
            why[k++] = abi.decode(logs[i].data, (bytes4));
        }
    }

    /// Hash of the Settled events of the router in the recorded logs.
    function _settledLogHash(StateVm.Log[] memory logs) internal view returns (bytes32 h) {
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].emitter != address(fairbind) || logs[i].topics.length == 0) continue;
            if (logs[i].topics[0] != SETTLED_TOPIC) continue;
            h = keccak256(abi.encode(h, logs[i].topics, logs[i].data));
        }
    }

    /// Hash of the values of `slots` of the router and the token.
    function _slotHash(bytes32[] memory rs, bytes32[] memory ts) internal view returns (bytes32 h) {
        for (uint256 i; i < rs.length; i++) h = keccak256(abi.encode(h, rs[i], stv.load(address(fairbind), rs[i])));
        for (uint256 i; i < ts.length; i++) h = keccak256(abi.encode(h, ts[i], stv.load(address(token), ts[i])));
    }

    function _concat(bytes32[] memory a, bytes32[] memory b) internal pure returns (bytes32[] memory c) {
        c = new bytes32[](a.length + b.length);
        for (uint256 i; i < a.length; i++) c[i] = a[i];
        for (uint256 i; i < b.length; i++) c[a.length + i] = b[i];
    }

    /// Runs the batch or the separate settle calls from the current state and
    /// returns the slots of the router and the token written, and the hash
    /// of the Settled events.
    function _run(FairBindCore.SettleItem[] memory items, bool batch)
        internal
        returns (bytes32[] memory rw, bytes32[] memory tw, bytes32 logs)
    {
        stv.record();
        stv.recordLogs();
        if (batch) sb.settleBatch(items);
        else _settleEach(items);
        logs = _settledLogHash(stv.getRecordedLogs());
        (, rw) = stv.accesses(address(fairbind));
        (, tw) = stv.accesses(address(token));
    }

    /// Whether the batch and the separate settle calls leave the same state
    /// (every slot either run wrote, in the router and the token) and the
    /// same Settled events.
    function _equivalent(FairBindCore.SettleItem[] memory items) internal returns (bool) {
        uint256 s0 = sw.snapshotState();
        (bytes32[] memory ra, bytes32[] memory ta, bytes32 la) = _run(items, true);
        sw.revertToState(s0);
        (bytes32[] memory rb, bytes32[] memory tb, bytes32 lb) = _run(items, false);
        bytes32[] memory r = _concat(ra, rb);
        bytes32[] memory t = _concat(ta, tb);
        bytes32 hb = _slotHash(r, t);
        sw.revertToState(s0);
        sb.settleBatch(items);
        bytes32 ha = _slotHash(r, t);
        return ha == hb && la == lb;
    }
}
