// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindBatch } from "../src/modules/FairBindBatch.sol";
import { FairBindBatchAdmin } from "../src/modules/FairBindBatchAdmin.sol";
import { FairBindProof } from "../src/modules/FairBindProof.sol";
import { FairBindDeposit } from "../src/modules/FairBindDeposit.sol";
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";
import { FairBindJudgment } from "../src/modules/FairBindJudgment.sol";
import { IVrfRandomness } from "../src/randomness/IVrfRandomness.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";

/// Mutation builds of the extension modules (ADR 0032 to ADR 0036). Each
/// breaks one rule a test checks.

/// The checkpoint of a fixed block reads the verifiers' current state.
contract CurrentStateBatch is FairBindBatchAdmin {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatchAdmin(token, gov, guard, treasury, pool)
    { }

    function _stateAt(uint32 id, uint256) internal view override returns (uint96, uint8, uint64) {
        VerifierView storage v = verifiers[id];
        return (uint96(v.bond), v.status, uint64(v.classBitmap));
    }
}

/// A ticket draws for the case's place in its batch list, so the opening
/// order and other cases change who is drawn.
contract OrderTicketBatch is FairBindBatch {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatch(token, gov, guard, treasury, pool)
    { }

    function _ticketCase(bytes32 caseId) internal view override returns (bytes32) {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        bytes32[] storage list = l.batches[purchases[en.ref].profileId][en.batch].cases;
        for (uint256 i; i < list.length; i++) {
            if (list[i] == caseId) return bytes32(i);
        }
        return caseId;
    }
}

/// A verifier's own exit request never moves a case.
contract NoMoveBatch is FairBindBatch {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatch(token, gov, guard, treasury, pool)
    { }

    function _moves(uint64, uint64) internal pure override returns (bool) {
        return false;
    }
}

/// A verifier's own exit request moves every case, also those fixed before it.
contract MoveAllBatch is FairBindBatch {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatch(token, gov, guard, treasury, pool)
    { }

    function _moves(uint64 departed, uint64) internal pure override returns (bool) {
        return departed != 0;
    }
}

/// The appeal deposit reads the held total of this block, after the
/// settlements that precede the appeal in it.
contract CurrentHeldProof is FairBindDeposit {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindDeposit(token, gov, guard, treasury, pool)
    { }

    function _appealHigh(uint32 bondId, uint32) internal view override returns (uint256) {
        BatchStore.HeldMark storage m = BatchStore.layout().held[bondId];
        return m.cur > m.prev ? m.cur : m.prev;
    }
}

/// A seller proof opens while a sample case of the account is still open.
contract EarlyProof is FairBindProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindProof(token, gov, guard, treasury, pool)
    { }

    function _proofReady(bytes32 nonce) internal view override returns (bool) {
        PurchaseView storage p = purchases[nonce];
        return anchors[p.sellerId][p.epoch].state == uint8(EpochState.SEALED);
    }
}

/// The compensation pool is shared by every account.
contract SharedPoolProof is FairBindProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindProof(token, gov, guard, treasury, pool)
    { }

    function _poolOf(uint32) internal pure override returns (uint32) {
        return 0;
    }
}

/// A split anchor's last unit may hold fewer entries than the rest of the count.
contract ShortUnitSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _unitLengthOk(uint256 length, uint256 expected) internal pure override returns (bool) {
        return length != 0 && length <= expected;
    }
}

/// A failed appeal pays the seller the whole proportional deposit.
contract ExcessToSellerJudgment is FairBindJudgment {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindJudgment(token, gov, guard, treasury, pool)
    { }

    function _resolveAppealDeposit(bytes32 nonce, uint8 result) internal override {
        BatchStore.layout().depositExcess[nonce] = 0;
        super._resolveAppealDeposit(nonce, result);
    }
}

/// A sale needs the side-gain deposit of the open sales only, not one unit more.
contract SideGainShortSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _sideGainCovered(uint256 deposit, uint256 unit, uint256 open) internal pure override returns (bool) {
        return deposit >= unit * open;
    }
}

/// A queued sample case leaves its account's release clock running.
contract QueueNoPauseBatch is FairBindBatch {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatch(token, gov, guard, treasury, pool)
    { }

    function _queuePauses(CaseView storage) internal pure override returns (bool) {
        return false;
    }
}

/// A late batch value pauses only from the keeper's call.
contract LateStartNowAdmin is FairBindBatchAdmin {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatchAdmin(token, gov, guard, treasury, pool)
    { }

    function _lateStart(uint256) internal view override returns (uint256) {
        return block.number;
    }
}

/// The exit of an unanswered value opens after D_V, without T_V.
contract EarlyExitAdmin is FairBindBatchAdmin {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatchAdmin(token, gov, guard, treasury, pool)
    { }

    function _exitOpen(IVrfRandomness vrf, uint64 requested) internal view override returns (bool) {
        return block.number > uint256(requested) + vrf.responseBlocks();
    }
}

/// An unanswered review of a seller's appeal ends without a count.
contract SellerAppealExitDeposit is FairBindDeposit {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindDeposit(token, gov, guard, treasury, pool)
    { }

    function _upholdsFirstFail(CaseView storage) internal pure override returns (bool) {
        return false;
    }
}

/// A late AUX value pauses only from the keeper's call.
contract LateStartNowBatch is FairBindBatch {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatch(token, gov, guard, treasury, pool)
    { }

    function _lateStart(uint256) internal view override returns (uint256) {
        return block.number;
    }
}

/// A late sampling value pauses only from the keeper's call.
contract LateStartNowProof is FairBindProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindProof(token, gov, guard, treasury, pool)
    { }

    function _lateStart(uint256) internal view override returns (uint256) {
        return block.number;
    }
}
