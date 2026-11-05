// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../../src/FairBind.sol";
import { FairBindRegistry } from "../../src/modules/FairBindRegistry.sol";
import { FairBindSettlement } from "../../src/modules/FairBindSettlement.sol";
import { FairBindSampling } from "../../src/modules/FairBindSampling.sol";
import { FairBindDelivery } from "../../src/modules/FairBindDelivery.sol";
import { FairBindPublication } from "../../src/modules/FairBindPublication.sol";
import { FairBindRecovery } from "../../src/modules/FairBindRecovery.sol";
import { FairBindJudgment } from "../../src/modules/FairBindJudgment.sol";
import { FairBindReview } from "../../src/modules/FairBindReview.sol";
import { FairBindBond } from "../../src/modules/FairBindBond.sol";
import { FairBindLens } from "../../src/modules/FairBindLens.sol";
import { AdmissionOverrideRegistry } from "../AdmissionOverrideRegistry.sol";
import { ArtifactDeploy } from "../DeployFairBind.sol";

// Mutation build: the judgment and review modules, which place the freeze on
// the judged path, with the bond-level freeze switched off. The seller is
// still suspended and failures are still counted, but a judged failure no
// longer holds the other deferred entries of the bond account. This restores
// the refund rule in force before ADR 0012, in which only a judged purchase is
// refunded and every other purchase of a failing seller is released to it.
// It exists only in tests.

contract NoFreezeJudgment is FairBindJudgment {
    constructor(address a, address b, address c, address d, address e) FairBindJudgment(a, b, c, d, e) { }
    function _freezeEnabled() internal pure override returns (bool) { return false; }
}
contract NoFreezeReview is FairBindReview {
    constructor(address a, address b, address c, address d, address e) FairBindReview(a, b, c, d, e) { }
    function _freezeEnabled() internal pure override returns (bool) { return false; }
}

abstract contract DeployFairBindWithoutFreeze {
    function deployFairBindWithoutFreeze(address token, address gov, address guard, address treasury, address pool)
        internal
        returns (FairBind)
    {
        // The comparison profiles freeze at the initial FAIL, which only the
        // admission-override registry admits.
        return ArtifactDeploy.deploy(token, gov, guard, treasury, pool,
            "AdmissionOverrideRegistry.sol:AdmissionOverrideRegistry", "FreezeDisabled.sol:NoFreezeJudgment",
            "FreezeDisabled.sol:NoFreezeReview");
    }
}
