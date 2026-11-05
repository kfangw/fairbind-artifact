// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindRegistry } from "../src/modules/FairBindRegistry.sol";
import { FairBindExchange } from "../src/modules/FairBindExchange.sol";
import { FairBindRecovery } from "../src/modules/FairBindRecovery.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { IVrfRandomness } from "../src/randomness/IVrfRandomness.sol";

/// Mutation builds of admission checks 6, 7 and 8, the batched hold and the
/// keeper slack (rules D2-13 (c), D2-8 (a)), of the binding proof start
/// (rule D2-19 (g)) and of the SAMPLE request (rule D2-23 (a)). Each breaks
/// one rule a test checks.

/// Activation does not check that the binding proof window outlasts the
/// wait for the sampling value.
contract AnyWindowRegistry is FairBindRegistry {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindRegistry(token, gov, guard, treasury, pool)
    { }

    function _bindOpenFits(ServiceProfileInput storage, ExchangeStore.Terms storage)
        internal
        pure
        override
        returns (bool)
    {
        return true;
    }
}

/// Activation of a batched profile does not check its hold against L_F.
contract ShortBatchHoldRegistry is FairBindRegistry {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindRegistry(token, gov, guard, treasury, pool)
    { }

    function _batchHorizonHolds(ServiceProfileInput storage, uint32) internal pure override returns (bool) {
        return true;
    }
}

/// Activation takes any F_max, also one below L_F + marginBlocks - 1.
contract AnyRangeRegistry is FairBindRegistry {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindRegistry(token, gov, guard, treasury, pool)
    { }

    function _bindWindowInRange(ServiceProfileInput storage, ExchangeStore.Terms storage, uint256)
        internal
        pure
        override
        returns (bool)
    {
        return true;
    }
}

/// The terms take a binding proof window longer than T_keep.
contract ShortKeepExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _keepCoversWindow(ServiceProfileInput storage, ExchangeStore.Input calldata)
        internal
        pure
        override
        returns (bool)
    {
        return true;
    }
}

/// A binding proof waits for the epoch's SAMPLE value (the start that rule
/// D2-19 (h) once put on it).
contract ValueStartRecovery is FairBindRecovery {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindRecovery(token, gov, guard, treasury, pool)
    { }

    function _bindingProofOpen(PurchaseView storage purchase, AnchorView storage anchorRecord)
        internal
        view
        override
        returns (bool)
    {
        IVrfRandomness vrf = _vrfAt(anchorRecord.anchoredBlock);
        uint64 a = _anchorDeadline(profiles[purchase.profileId].parameters, purchase.epoch);
        return super._bindingProofOpen(purchase, anchorRecord) && address(vrf) != address(0)
            && _sampleValue(vrf, purchase.profileId, a) != bytes32(0);
    }
}

/// The SAMPLE request needs an account of the profile that anchored the
/// epoch.
contract AnchoredSampleRecovery is FairBindRecovery {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindRecovery(token, gov, guard, treasury, pool)
    { }

    function _sampleRequestWindow(IVrfRandomness vrf, uint32 profileId, uint24 epoch)
        internal
        view
        override
        returns (uint64 anchorDeadline, uint64 deadline)
    {
        (anchorDeadline, deadline) = super._sampleRequestWindow(vrf, profileId, epoch);
        for (uint32 s = 1; s < nextSellerId; s++) {
            AnchorView storage a = anchors[s][epoch];
            if (a.root != bytes32(0) && a.profileId == profileId) return (anchorDeadline, deadline);
        }
        revert RequestTooEarly();
    }
}
