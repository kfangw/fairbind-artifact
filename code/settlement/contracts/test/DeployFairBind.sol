// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../src/FairBind.sol";
import { FairBindRegistry } from "../src/modules/FairBindRegistry.sol";
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";
import { FairBindSampling } from "../src/modules/FairBindSampling.sol";
import { FairBindDelivery } from "../src/modules/FairBindDelivery.sol";
import { FairBindPublication } from "../src/modules/FairBindPublication.sol";
import { FairBindRecovery } from "../src/modules/FairBindRecovery.sol";

import { FairBindJudgment } from "../src/modules/FairBindJudgment.sol";
import { FairBindReview } from "../src/modules/FairBindReview.sol";
import { FairBindBond } from "../src/modules/FairBindBond.sol";
import { FairBindLens } from "../src/modules/FairBindLens.sol";
import { AnchorLeaves } from "./AnchorLeaves.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";

interface ArtifactVm {
    function deployCode(string calldata artifact, bytes calldata args) external returns (address);
}

/// Deploys FairBind and its modules from their compiled artifacts, so that a
/// test contract does not embed their creation code. Embedding all ten
/// modules in every test contract made one via-IR compilation exceed the
/// memory of the reference machine (ADR 0025). The imports keep the artifacts
/// built when a filter selects only some test files.
library ArtifactDeploy {
    ArtifactVm internal constant vm = ArtifactVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    /// Module artifacts in constructor order; `registry` replaces the registry
    /// module and `judgment` and `review` replace theirs when not empty.
    function deploy(
        address token,
        address gov,
        address guard,
        address treasury,
        address pool,
        string memory registry,
        string memory judgment,
        string memory review
    ) internal returns (FairBind) {
        bytes memory args = abi.encode(token, gov, guard, treasury, pool);
        string[10] memory names = [
            bytes(registry).length != 0 ? registry : "FairBindRegistry.sol:FairBindRegistry",
            "FairBindSettlement.sol:FairBindSettlement",
            "FairBindSampling.sol:FairBindSampling",
            "FairBindDelivery.sol:FairBindDelivery",
            "FairBindPublication.sol:FairBindPublication",
            "FairBindRecovery.sol:FairBindRecovery",
            bytes(judgment).length != 0 ? judgment : "FairBindJudgment.sol:FairBindJudgment",
            bytes(review).length != 0 ? review : "FairBindReview.sol:FairBindReview",
            "FairBindBond.sol:FairBindBond",
            "FairBindLens.sol:FairBindLens"
        ];
        address[10] memory modules;
        for (uint256 i; i < 10; i++) modules[i] = vm.deployCode(names[i], args);
        return FairBind(vm.deployCode("FairBind.sol:FairBind", abi.encode(token, gov, guard, treasury, pool, modules)));
    }
}

abstract contract DeployFairBind {
    address internal constant REWARD_POOL = address(0xB0B0);
    function deployFairBind(address token, address gov, address guard, address treasury)
        internal
        returns (FairBind)
    {
        return ArtifactDeploy.deploy(token, gov, guard, treasury, REWARD_POOL, "", "", "");
    }

    /// Registers a bond account of the given amount and one seller under it.
    function registerSellerWithBond(
        FairBind fairbind,
        uint32 profileId,
        address signingKey,
        bytes32 claimsHash,
        uint128 amount
    ) internal returns (uint32 sellerId) {
        uint32 bondId = fairbind.registerBond(profileId, amount);
        sellerId = fairbind.registerSeller(bondId, profileId, signingKey, claimsHash);
    }

    // The anchor carries its (nonce, receiptLeaf) list in nonce order
    // (ADR 0026). These build that list and its root off chain.

    function _anchorRoot(FairBindMerkle.ReceiptEntry[] memory entries) internal pure returns (bytes32) {
        return AnchorLeaves.rootOf(entries);
    }

    /// One filler entry derived from `seed`; it is no purchase's entry.
    function _oneEntry(bytes32 seed) internal pure returns (FairBindMerkle.ReceiptEntry[] memory) {
        return AnchorLeaves.one(seed);
    }

    /// `count` filler entries derived from `seed`, in ascending nonce order.
    function _filledEntries(bytes32 seed, uint256 count)
        internal
        pure
        returns (FairBindMerkle.ReceiptEntry[] memory)
    {
        return AnchorLeaves.filled(seed, count);
    }

    /// The one-entry list (nonce, receiptLeaf).
    function _pairEntry(bytes32 nonce, bytes32 receiptLeaf)
        internal
        pure
        returns (FairBindMerkle.ReceiptEntry[] memory)
    {
        return AnchorLeaves.pair(nonce, receiptLeaf);
    }
}
