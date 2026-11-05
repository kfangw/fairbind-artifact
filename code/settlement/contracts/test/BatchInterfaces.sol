// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";

/// Router selectors of the four extension modules (ADR 0032 to ADR 0035).
interface IBatchedFairBind {
    function setExtensions(address[] calldata list) external;
    function setBatchTerms(uint32 profileId, BatchStore.Terms calldata t) external;
    function checkpointAt(uint32 profileId, uint24 epoch) external returns (uint64);
    function recordEpochOpenCount(uint32 profileId, uint24 epoch) external returns (uint32);
    function requestAssignValue(uint32 profileId, uint24 epoch) external;
    function assignBatch(uint32 profileId, uint24 epoch) external;
    function markAssignLate(uint32 profileId, uint24 epoch) external;
    function timeoutAssignValue(uint32 profileId, uint24 epoch) external;
    function requestLateValue(bytes32 nonce) external;
    function assignLate(bytes32 nonce) external;
    function timeoutLateValue(bytes32 nonce) external;
    function transferQueued(bytes32 caseId) external;
    function withdrawVerifierBond(uint32 verifierId, uint128 amount) external;
    function hook(uint256 op, uint256 arg) external;
    function getBatchTerms(uint32 profileId) external view returns (BatchStore.Terms memory);
    function getBatch(uint32 profileId, uint24 epoch)
        external
        view
        returns (bytes32 value, uint64 valueBlock, uint64 checkpointVersion, bool assigned, bool exited, bytes32[] memory list);
    function getBatchEntry(bytes32 caseId) external view returns (BatchStore.Entry memory);
    function getQueue(uint32 verifierId) external view returns (bytes32[] memory);
    function getSlots(uint32 verifierId) external view returns (BatchStore.Slots memory s, uint256 slots);
    function verifierStateAt(uint32 verifierId, uint64 x) external view returns (uint96, uint8, uint64);
    function batchClose(uint32 profileId, uint24 epoch) external view returns (uint256);
    function batchOf(uint32 profileId, uint64 atBlock) external view returns (uint24);
    function proofCaseId(bytes32 nonce) external pure returns (bytes32);

    function appealWithLimit(bytes32 nonce, uint256 maxDeposit) external;
    function appealDepositOf(bytes32 nonce) external view returns (uint256 d, uint256 high);
    function setProofsOff(uint32 bondId, bool off) external;
    function submitProof(
        bytes32 nonce,
        FairBindCore.FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        FairBindCore.ReceiptProof calldata proof,
        bytes calldata evidence
    ) external;
    function activateProof(bytes32 nonce) external;
    function voidReservation(bytes32 nonce) external;
    function requestAuditValue(bytes32 nonce) external;
    function drawAudit(bytes32 nonce) external;
    function timeoutAuditValue(bytes32 nonce) external;
    function contestProof(bytes32 nonce) external;
    function confirmProof(bytes32 nonce) external;
    function judgeProof(bytes32 nonce, uint8 verdict, bytes calldata signature) external;
    function timeoutProofJudge(bytes32 nonce) external;
    function releaseProven(bytes32 nonce) external;
    function distributeCompensation(uint32 bondId) external;
    function claimCompensation(bytes32 nonce) external;
    function depositSideGain(uint32 bondId, uint128 amount) external;
    function withdrawSideGain(uint32 bondId, uint128 amount) external;
    function clearSideGain(bytes32 nonce) external;
    function rerequestSampleValue(uint32 profileId, uint24 epoch) external;
    function noteSampleDeadline(uint32 sellerId, uint24 epoch) external;
    function proofVerdictDigest(bytes32 nonce, uint8 verdict) external view returns (bytes32);
    function getProof(bytes32 nonce) external view returns (BatchStore.Proof memory);
    function getProofAccount(uint32 bondId) external view returns (BatchStore.ProofAccount memory);
    function getPool(uint32 bondId) external view returns (BatchStore.Pool memory);
    function getSideGain(uint32 bondId) external view returns (BatchStore.SideGain memory);
    function proofBondOf(bytes32 nonce) external view returns (uint256);
    function proofReady(bytes32 nonce) external view returns (bool);
    function requestReviewValue(bytes32 nonce) external;
    function assignReview(bytes32 nonce) external;
    function timeoutReviewValue(bytes32 nonce) external;
    function markValueLate(bytes32 nonce) external;
    function markSampleLate(uint32 sellerId, uint24 epoch) external;
    function getReviewUse(bytes32 nonce) external view returns (BatchStore.ReviewUse memory);
}
