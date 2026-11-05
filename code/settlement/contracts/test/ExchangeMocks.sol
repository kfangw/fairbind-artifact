// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IUniquePriceUpdates } from "../src/oracle/IUniquePriceUpdates.sol";

/// Test stand-in for a signed price-update verifier with the Unique
/// semantics of rule D2-30 (a). An update is
/// abi.encode(id, price, conf, expo, publishTime, prevPublishTime, signature)
/// with the guardian's signature over keccak256 of the first six fields. The
/// call returns the update's price when the signature holds, the id is the
/// asked one, minPublishTime <= publishTime <= maxPublishTime and
/// prevPublishTime < minPublishTime (no earlier update after the minimum);
/// it reverts otherwise. Real Pyth updates carry a Wormhole VAA and a merkle
/// path instead; the measured cost of that check is in the C measurement.
contract MockUniquePriceFeed is IUniquePriceUpdates {
    address public immutable guardian;

    error BadUpdate();

    constructor(address guardian_) {
        guardian = guardian_;
    }

    function updateDigest(bytes32 id, int64 price, uint64 conf, int32 expo, uint64 publishTime, uint64 prevPublishTime)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(id, price, conf, expo, publishTime, prevPublishTime));
    }

    function parsePriceFeedUpdatesUnique(
        bytes[] calldata updateData,
        bytes32[] calldata priceIds,
        uint64 minPublishTime,
        uint64 maxPublishTime
    ) external payable returns (PriceFeed[] memory feeds) {
        if (updateData.length != 1 || priceIds.length != 1) revert BadUpdate();
        (bytes32 id, int64 price, uint64 conf, int32 expo, uint64 publishTime, uint64 prev, bytes memory sig) =
            abi.decode(updateData[0], (bytes32, int64, uint64, int32, uint64, uint64, bytes));
        if (id != priceIds[0] || publishTime < minPublishTime || publishTime > maxPublishTime || prev >= minPublishTime) {
            revert BadUpdate();
        }
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 0x20))
            s := mload(add(sig, 0x40))
            v := byte(0, mload(add(sig, 0x60)))
        }
        if (ecrecover(updateDigest(id, price, conf, expo, publishTime, prev), v, r, s) != guardian) revert BadUpdate();
        feeds = new PriceFeed[](1);
        feeds[0].id = id;
        feeds[0].price = Price(price, conf, expo, publishTime);
        feeds[0].emaPrice = Price(price, conf, expo, publishTime);
    }
}

/// Test stand-in for the OP Stack GasPriceOracle predeploy: the L1 fee of
/// `data` is max(floor, (16 * nonzero + 4 * zero bytes + 68 * 16) *
/// feePerUnit), so that one transaction's fixed floor is visible.
contract MockGasPriceOracle {
    uint256 public feePerUnit;
    uint256 public floor;
    bool public boundOff;

    function set(uint256 feePerUnit_, uint256 floor_) external {
        feePerUnit = feePerUnit_;
        floor = floor_;
    }

    /// A chain before Fjord: getL1FeeUpperBound reverts.
    function setBoundOff(bool off) external {
        boundOff = off;
    }

    /// The content-dependent fee (a calldata-gas model, not FastLZ); only the
    /// mutation build that prices the L1 share by content calls it.
    function getL1Fee(bytes calldata data) external view returns (uint256) {
        uint256 units = 68 * 16;
        for (uint256 i; i < data.length; i++) units += data[i] == 0 ? 4 : 16;
        uint256 fee = units * feePerUnit;
        return fee < floor ? floor : fee;
    }

    /// The Fjord GasPriceOracle.getL1FeeUpperBound formula (OP Stack
    /// contracts-bedrock, src/L2/GasPriceOracle.sol): 68 signature bytes are
    /// added, the FastLZ size is bounded by size + size / 255 + 16, the
    /// Brotli estimate is -42.5856 + 0.8365 * that size bytes with a floor of
    /// 100 bytes, and the fee is the estimate times 16 * feePerUnit (in place
    /// of baseFeeScalar * 16 * l1BaseFee + blobBaseFeeScalar * blobBaseFee,
    /// scaled down by 1e12).
    function getL1FeeUpperBound(uint256 unsignedTxSize) external view returns (uint256) {
        require(!boundOff, "GasPriceOracle: getL1FeeUpperBound only supports Fjord");
        uint256 txSize = unsignedTxSize + 68;
        uint256 flz = txSize + txSize / 255 + 16;
        int256 est = -42_585_600 + int256(836_500 * flz);
        if (est < 100 * 1e6) est = 100 * 1e6;
        return uint256(est) * 16 * feePerUnit / 1e6;
    }
}

/// A smart-account payer or seller key: ERC-1271 accepts the owner's
/// signatures until revoked; `burn` makes it spend gas first.
contract Mock1271Wallet {
    address public owner;
    bool public revoked;
    uint256 public burn;

    constructor(address owner_) {
        owner = owner_;
    }

    function setRevoked(bool r) external {
        revoked = r;
    }

    function setBurn(uint256 b) external {
        burn = b;
    }

    function isValidSignature(bytes32 hash, bytes calldata sig) external view returns (bytes4) {
        uint256 g = gasleft();
        while (burn != 0 && g - gasleft() < burn) { }
        if (revoked || sig.length < 65) return 0xffffffff;
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 32))
            v := byte(0, calldataload(add(sig.offset, 64)))
        }
        return ecrecover(hash, v, r, s) == owner ? bytes4(0x1626ba7e) : bytes4(0xffffffff);
    }
}

/// Runs several calls to one target in a single transaction.
contract MultiCall {
    function run(address target, bytes[] calldata calls) external {
        for (uint256 i; i < calls.length; i++) {
            (bool ok, bytes memory ret) = target.call(calls[i]);
            if (!ok) {
                assembly {
                    revert(add(ret, 0x20), mload(ret))
                }
            }
        }
    }
}
