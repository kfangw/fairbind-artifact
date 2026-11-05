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
import { ArtifactDeploy } from "./DeployFairBind.sol";

// Test build for deferral sweeps: the registry module with the admission
// override switched on. Profile creation then skips exactly three checks,
// retentionBlocks >= caseHorizon (and with it deferBlocks >= caseHorizon),
// deferBlocks >= retentionBlocks and enforcementBlocks >= judgmentDelayBlocks,
// so a sweep point with a hold period below the case horizon can be deployed.
// Every other admission rule still applies. It exists only for tests and
// local experiments; scripts/local_deploy.py deploys it in place of
// FairBindRegistry only when asked for the admission override build.

contract AdmissionOverrideRegistry is FairBindRegistry {
    constructor(address a, address b, address c, address d, address e) FairBindRegistry(a, b, c, d, e) { }
    function _admissionOverride() internal pure override returns (bool) { return true; }
}

abstract contract DeployFairBindWithAdmissionOverride {
    function deployFairBindWithAdmissionOverride(
        address token,
        address gov,
        address guard,
        address treasury,
        address pool
    ) internal returns (FairBind) {
        return ArtifactDeploy.deploy(token, gov, guard, treasury, pool,
            "AdmissionOverrideRegistry.sol:AdmissionOverrideRegistry", "", "");
    }
}
