// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";

/// Router selectors of the receipt-signature and proof modules (ADR 0037).
interface IExchangeFairBind {
    function setExtensions(address[] calldata list) external;
    function setExchangeTerms(uint32 profileId, ExchangeStore.Input calldata x) external;
    function exchangeTermsHash(uint32 profileId, ExchangeStore.Input calldata x) external pure returns (bytes32);
    function postReceipt(ExchangeStore.Post calldata post, bytes calldata sellerSig) external;
    function postReceipts(ExchangeStore.Post[] calldata posts, bytes calldata sellerSig) external;
    function matchAnchor(ExchangeStore.Match[] calldata matches) external;
    function refundUnbound(bytes32 nonce) external;
    function discloseKey(bytes32 nonce, bool recovery, bytes32 ek, bytes calldata ct, bytes32 leaf) external;
    function getExchangeTerms(uint32 profileId) external view returns (ExchangeStore.Terms memory);
    function getExchangeRecord(bytes32 nonce)
        external
        view
        returns (bytes32 bundle, ExchangeStore.Record memory record, ExchangeStore.Ladder memory ladder);
    function receiptSignatureDigest(bytes32 nonce, bytes32 ctHash, bytes32 ekHash, bytes32 rHash, bytes32 leaf)
        external
        view
        returns (bytes32);
    function postDigest(ExchangeStore.Post calldata post) external view returns (bytes32);
    function postListDigest(uint32 profileId, bytes32 listHash, uint256 count) external view returns (bytes32);
    function proofCommitment(bytes32 nonce) external view returns (bytes32);
    function requireExchangeTerms() external;

    function openProofSample(bytes32 nonce) external;
    function openProofDispute(bytes32 nonce, uint8 kind) external;
    function prove(bytes32 nonce, uint8 flags, ExchangeStore.PassProof calldata q) external;
    function proveAbsence(bytes32 nonce, bytes calldata update) external;
    function timeoutProof(bytes32 nonce) external;
    function selfProve(bytes32 nonce) external;
    function activateSelfProof(bytes32 nonce) external;
    function voidSelfProof(bytes32 nonce) external;
    function releaseSelfProven(bytes32 nonce) external;
    function selfProofReady(bytes32 nonce) external view returns (bool);
}
