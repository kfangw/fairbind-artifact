// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// The signed price-update verifier a proof profile names (rule D2-28 (b),
/// UNIQUE input): for the given feeds it returns, from signed update data,
/// the first update published at or after minPublishTime, and reverts when
/// the data holds no such update at or before maxPublishTime or when an
/// earlier update exists (its previous publish time is not below
/// minPublishTime). The shape is that of a Pyth Core contract's
/// parsePriceFeedUpdatesUnique.
interface IUniquePriceUpdates {
    struct Price {
        int64 price;
        uint64 conf;
        int32 expo;
        uint256 publishTime;
    }

    struct PriceFeed {
        bytes32 id;
        Price price;
        Price emaPrice;
    }

    function parsePriceFeedUpdatesUnique(
        bytes[] calldata updateData,
        bytes32[] calldata priceIds,
        uint64 minPublishTime,
        uint64 maxPublishTime
    ) external payable returns (PriceFeed[] memory priceFeeds);
}
