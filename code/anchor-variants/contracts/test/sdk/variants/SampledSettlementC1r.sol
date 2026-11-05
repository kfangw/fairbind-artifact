// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IAuthToken } from "../SampledSettlement.sol";
import { SampledSettlementC1Core } from "./SampledSettlementC1.sol";

/// Variant C1r: as C1, with the slots keyed by (profile, epoch mod (k + 3),
/// unit number) and tagged with their epoch. A later epoch writes a slot
/// again (non-zero to non-zero) once the account's cursor has passed the
/// epoch that left it; while the cursor has not, the record goes to a
/// fallback slot keyed by the epoch itself. Proofs, disputes and swap proofs
/// of an epoch already end by the cursor's pass; the double-signature
/// evidence, which has no deadline in the reference contract, is accepted
/// here only until the cursor passes the epoch, and a missed anchor of a
/// passed epoch is left to the cursor's own record.
contract SampledSettlementC1r is SampledSettlementC1Core {
    constructor(IAuthToken token_, address randomness_, address module_)
        SampledSettlementC1Core(token_, randomness_, true, module_)
    { }
}
