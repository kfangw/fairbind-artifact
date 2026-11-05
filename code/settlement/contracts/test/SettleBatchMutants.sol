// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";

/// A failed item reverts the whole batch.
contract RevertAllSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _onItemFailure(bytes4) internal pure override {
        revert BondNotActive();
    }
}

/// The batch runs an item whatever gas is left.
contract NoGasCheckSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _itemGasOk(uint256) internal pure override returns (bool) {
        return true;
    }
}

/// The idempotency key is not checked.
contract NoKeyCheckSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _keyUsed(bytes32) internal pure override returns (bool) {
        return false;
    }
}

/// A failed item keeps its idempotency key marked: the item records the key
/// before its self call, outside the reverted frame.
contract KeepsKeySettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _runItem(SettleItem calldata item) internal override returns (bool ok, bytes4 reason) {
        (ok, reason) = super._runItem(item);
        if (!ok) {
            purchaseForKey[_deriveKeyId(item.sellerId, item.authorization.from, item.idempotencyKey)] = bytes32(uint256(1));
        }
    }
}

/// Settlements leave the transient cost mark unset.
contract NoMarkSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _markCost() internal pure override { }
}
