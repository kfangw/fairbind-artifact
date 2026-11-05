// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSettlement } from "../../src/modules/FairBindSettlement.sol";
import { FairBindSampling } from "../../src/modules/FairBindSampling.sol";
import { FairBindDelivery } from "../../src/modules/FairBindDelivery.sol";
import { FairBindPublication } from "../../src/modules/FairBindPublication.sol";
import { FairBindRecovery } from "../../src/modules/FairBindRecovery.sol";
import { FairBindJudgment } from "../../src/modules/FairBindJudgment.sol";
import { FairBindReview } from "../../src/modules/FairBindReview.sol";
import { FairBindBond } from "../../src/modules/FairBindBond.sol";

// Wide-freeze mutation build (ADR 0030): every module that can reach _freeze
// starts the freeze at block zero instead of the settlement block of the
// failing sale, which holds every unreleased entry of the account as ADR 0012
// did. Entries settled before the failing sale are then refused at release,
// claimable from the frozen pool and forfeited with the window. The stateful
// suite, whose model follows the narrow freeze, must catch it. It exists only
// in tests.

contract WideFreezeSettlement is FairBindSettlement {
    constructor(address a, address b, address c, address d, address e) FairBindSettlement(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeSampling is FairBindSampling {
    constructor(address a, address b, address c, address d, address e) FairBindSampling(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeDelivery is FairBindDelivery {
    constructor(address a, address b, address c, address d, address e) FairBindDelivery(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezePublication is FairBindPublication {
    constructor(address a, address b, address c, address d, address e) FairBindPublication(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeRecovery is FairBindRecovery {
    constructor(address a, address b, address c, address d, address e) FairBindRecovery(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeJudgment is FairBindJudgment {
    constructor(address a, address b, address c, address d, address e) FairBindJudgment(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeReview is FairBindReview {
    constructor(address a, address b, address c, address d, address e) FairBindReview(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
contract WideFreezeBond is FairBindBond {
    constructor(address a, address b, address c, address d, address e) FairBindBond(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
