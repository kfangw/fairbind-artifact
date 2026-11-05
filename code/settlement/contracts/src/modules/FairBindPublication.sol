// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Rule8Store } from "./Rule8Store.sol";
import { FairBindCore } from "../FairBindCore.sol";
import { IRandomness } from "../randomness/IRandomness.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";

contract FairBindPublication is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 5;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    // The epoch transitions after the anchor (seal, the checkpoint-shortage
    // exit and the missed-anchor timeout) live here, apart from the sampling
    // module, which keeps the case-opening and assignment paths below the size
    // limit.
    function timeoutAnchor(uint32 sellerId, uint24 epoch) external onlyDelegateCall nonReentrant {
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.NONE) || epochPurchaseCount[sellerId][epoch] == 0) {
            revert InvalidTransition();
        }
        SellerView storage seller = sellers[sellerId].viewData;
        ServiceProfileInput storage profile = profiles[seller.profileId].parameters;
        uint256 deadline =
            _anchorBase(profile, epoch) + deadlineConfigs[profile.deadlineConfigId].anchorBlocks;
        if (block.number <= deadline) revert DeadlineNotReached();
        record.profileId = seller.profileId;
        record.count = epochPurchaseCount[sellerId][epoch];
        record.state = uint8(EpochState.EPOCH_FAILED);
        emit EpochFailed(sellerId, epoch, uint8(EpochFailureReason.ANCHOR_TIMEOUT));
        _epochResolved(sellerId, epoch);
        // A missed anchor is the seller's failure: it counts once and freezes at once.
        epochFailureCounted[sellerId][epoch] = true;
        _confirmFailure(sellerId, bytes32(0), true, _epochStart(profile, epoch));
        _r8Fee(seller.profileId, Rule8Store.FEE_ANCHOR_TIMEOUT);
    }

    /// Delivers the sampling value of an anchored epoch (design 2 rule D2-16,
    /// ADR 0029). Anyone may call it after randomBlock, also after
    /// sealDeadline, while the chain still serves blockhash(randomBlock); a
    /// late value takes the normal path. Without the value the call reverts
    /// and the epoch stays ANCHORED: none of its entries is released, nothing
    /// is counted against the seller, and only the checkpoint shortage of
    /// timeoutSeal ends it.
    function seal(uint32 sellerId, uint24 epoch) external onlyDelegateCall {
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.ANCHORED)) revert InvalidTransition();
        // Rule 8: the seal is that of the profile epoch (rule D2-35 (a), (b));
        // this only copies it into the record and delays no verifier exit.
        if (_r8Hook(record.profileId, HOOK_R8_SEAL, (uint256(sellerId) << 24) | epoch)) return;
        if (block.number <= record.randomBlock) revert DeadlineNotReached();
        ServiceProfileInput storage sealProfile = profiles[record.profileId].parameters;
        uint64 anchorDeadline = _anchorDeadline(sealProfile, epoch);
        bytes32 randomness;
        IRandomness source = _sourceAt(record.anchoredBlock);
        if (address(source) == address(0)) {
            randomness = blockhash(record.randomBlock);
        } else if (SamplingStore.layout().randomness.vrf) {
            // The value of the SAMPLE request (profile, A), stored by block
            // A + D_S + T_V at the latest (rule D2-23 (d), ADR 0031).
            randomness = _sampleValue(IVrfRandomness(address(source)), record.profileId, anchorDeadline);
            // A side-gain profile takes the value of the repeated request
            // asked for after M (ADR 0035).
            if (randomness == bytes32(0) && BatchStore.layout().terms[record.profileId].sideGainPpm != 0) {
                randomness = _repeatedSampleValue(IVrfRandomness(address(source)), record.profileId, anchorDeadline);
            }
        } else {
            bool ready;
            (ready, randomness) = source.valueOf(anchorDeadline);
            if (!ready) randomness = bytes32(0);
        }
        if (randomness == bytes32(0)) revert InvalidRandomnessWindow();
        uint64 version = _checkpointAt(record.profileId, anchorDeadline);
        if (version == 0) revert ServiceClassUnavailable();
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[record.profileId][version];
        if (checkpoint.verifierIds.length < profiles[record.profileId].parameters.minVerifiers) {
            revert ServiceClassUnavailable();
        }
        // A batched epoch takes only the checkpoint of its anchor deadline (ADR 0032).
        if (_batched(record.profileId) && checkpoint.checkpointBlock != anchorDeadline) revert ServiceClassUnavailable();
        record.randomness = randomness;
        record.verifierSetHash = checkpoint.setHash;
        record.totalEffectiveWeight = checkpoint.totalEffectiveWeight;
        record.sortitionVersion = version;
        record.state = uint8(EpochState.SEALED);
        uint64 retainedUntil = epochRetainUntil[sellerId][epoch];
        for (uint256 i; i < checkpoint.verifierIds.length; i++) {
            VerifierView storage verifier = verifiers[checkpoint.verifierIds[i]];
            if (verifier.exitEligibleBlock < retainedUntil) {
                verifier.exitEligibleBlock = retainedUntil;
            }
        }
        emit EpochSealed(
            sellerId,
            epoch,
            randomness,
            checkpoint.setHash,
            version,
            checkpoint.totalEffectiveWeight
        );
        _epochResolved(sellerId, epoch);
    }

    /// The one end of an anchored epoch without its sampling value (design 2
    /// rule D2-16 (f), ADR 0029). Once the epoch's checkpoint is fixed, after
    /// the anchor deadline, anyone may end the epoch as EPOCH_FAILED (reason
    /// VERIFIER_SET_UNAVAILABLE) if that checkpoint, the latest written at or
    /// before the anchor deadline, is missing or holds fewer than
    /// minVerifiers verifiers; seal can then never succeed. It does not wait
    /// for the value. The checkpoint precedes the value, so the seller cannot
    /// send an epoch here after seeing its sample. claimEpochFailure refunds
    /// its purchases without a seller failure. Otherwise the call reverts
    /// InvalidTransition and the epoch keeps waiting for its value. The name
    /// is kept from the seal timeout this replaces.
    function timeoutSeal(uint32 sellerId, uint24 epoch) external onlyDelegateCall {
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.ANCHORED)) revert InvalidTransition();
        // Rule 8: the checkpoint shortage is confirmed once per profile epoch
        // (rule D2-35 (c)); this only copies its end into the record.
        if (_r8Hook(record.profileId, HOOK_R8_SEAL_FAIL, (uint256(sellerId) << 24) | epoch)) return;
        ServiceProfileInput storage profile = profiles[record.profileId].parameters;
        uint64 anchorDeadline = _anchorDeadline(profile, epoch);
        if (block.number <= anchorDeadline) revert DeadlineNotReached();
        uint64 version = _checkpointAt(record.profileId, anchorDeadline);
        if (_batched(record.profileId)) {
            // Only the checkpoint of block A counts (ADR 0032). Without it the
            // epoch waits for it, unless a later checkpoint makes it unwritable.
            if (version == 0 || verifierCheckpoints[record.profileId][version].checkpointBlock != anchorDeadline) {
                uint64 latest = latestCheckpointVersion[record.profileId];
                if (verifierCheckpoints[record.profileId][latest].checkpointBlock <= anchorDeadline) revert DeadlineNotReached();
                version = 0;
            }
        }
        if (version != 0 && verifierCheckpoints[record.profileId][version].verifierIds.length >= profile.minVerifiers) {
            revert InvalidTransition();
        }
        record.state = uint8(EpochState.EPOCH_FAILED);
        emit EpochFailed(sellerId, epoch, uint8(EpochFailureReason.VERIFIER_SET_UNAVAILABLE));
        _epochResolved(sellerId, epoch);
    }

    function publish(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        bytes calldata responseBody,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external onlyDelegateCall nonReentrant {
        uint256 g0 = gasleft();
        _publicationAccess(nonce);
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        if (responseBody.length > profile.maxResponseBytes) revert ResponseTooLarge();
        _validatePublishedRequest(purchase, nonce, idempotencyKey, request, profile.maxRequestBytes);
        _validateReceipt(purchase, nonce, receipt, receiptSignature);
        bytes32 responseHash = _responseHash(responseBody);
        if (responseHash != receipt.responseHash) revert InvalidPublication();
        _finishPublication(
            nonce,
            responseHash,
            uint16(_chunkCount(responseBody.length)),
            uint32(responseBody.length)
        );
        if (_ladderOn(nonce, false)) {
            _ladderCost(nonce, false, g0,
                abi.encodeWithSelector(msg.sig, nonce, idempotencyKey, request, responseBody, receipt, receiptSignature));
        }
    }

    function beginPublication(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        uint32 totalBytes,
        uint16 chunkCount
    ) external onlyDelegateCall {
        uint256 g0 = gasleft();
        _publicationAccess(nonce);
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        if (totalBytes > profile.maxResponseBytes) revert ResponseTooLarge();
        // A measured ladder takes each stage once (rule D2-24 (d') 2).
        bool measured = _ladderOn(nonce, false);
        if (measured && publications[nonce].chunkCount != 0) revert InvalidPublication();
        if (chunkCount != _chunkCount(totalBytes)) revert InvalidPublication();
        _validatePublishedRequest(purchase, nonce, idempotencyKey, request, profile.maxRequestBytes);
        _validateReceipt(purchase, nonce, receipt, receiptSignature);
        Publication storage publication = publications[nonce];
        delete publication.chunkHashes;
        cases[nonce].publishedChunks = 0;
        publication.responseHash = receipt.responseHash;
        publication.totalBytes = totalBytes;
        publication.bytesWritten = 0;
        publication.chunkCount = chunkCount;
        for (uint256 i; i < chunkCount; i++) {
            publication.chunkHashes.push(bytes32(0));
        }
        emit PublicationStarted(nonce, receipt.responseHash, chunkCount, totalBytes);
        if (measured) {
            _ladderCost(nonce, false, g0, abi.encodeWithSelector(
                msg.sig, nonce, idempotencyKey, request, receipt, receiptSignature, totalBytes, chunkCount));
        }
    }

    function publishChunk(bytes32 nonce, uint16 index, bytes calldata chunk)
        external
        onlyDelegateCall
    {
        uint256 g0 = gasleft();
        _publicationAccess(nonce);
        Publication storage publication = publications[nonce];
        if (publication.chunkCount == 0 || index >= publication.chunkCount) {
            revert InvalidPublication();
        }
        if (index != cases[nonce].publishedChunks) revert InvalidPublication();
        if (publication.chunkHashes[index] != bytes32(0)) revert InvalidPublication();
        uint256 expected = RESPONSE_CHUNK_BYTES;
        if (index + 1 == publication.chunkCount) {
            expected = publication.totalBytes - uint256(index) * RESPONSE_CHUNK_BYTES;
        }
        if (chunk.length != expected) revert InvalidPublication();
        publication.chunkHashes[index] = keccak256(chunk);
        publication.bytesWritten += uint32(chunk.length);
        cases[nonce].publishedChunks++;
        emit PublicationChunk(nonce, index, uint32(chunk.length));
        if (_ladderOn(nonce, false)) _ladderCost(nonce, false, g0, abi.encodeWithSelector(msg.sig, nonce, index, chunk));
    }

    function finalizePublication(bytes32 nonce) external onlyDelegateCall nonReentrant {
        uint256 g0 = gasleft();
        _publicationAccess(nonce);
        Publication storage publication = publications[nonce];
        if (
            publication.chunkCount == 0 || publication.bytesWritten != publication.totalBytes
                || cases[nonce].publishedChunks != publication.chunkCount
        ) revert InvalidPublication();
        bytes32 responseHash = _responseRoot(publication.chunkHashes);
        if (responseHash != publication.responseHash) revert InvalidPublication();
        _finishPublication(nonce, responseHash, publication.chunkCount, publication.totalBytes);
        if (_ladderOn(nonce, false)) _ladderCost(nonce, false, g0, abi.encodeWithSelector(msg.sig, nonce));
    }
    function publishBuyerResponse(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        bytes calldata responseBody,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external onlyDelegateCall nonReentrant {
        uint256 g0 = gasleft();
        _buyerPublicationAccess(nonce);
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        if (responseBody.length > profile.maxResponseBytes) revert ResponseTooLarge();
        _validatePublishedRequest(purchase, nonce, idempotencyKey, request, profile.maxRequestBytes);
        _validateReceipt(purchase, nonce, receipt, receiptSignature);
        bytes32 responseHash = _responseHash(responseBody);
        if (responseHash != receipt.responseHash) revert InvalidPublication();
        _finishBuyerPublication(
            nonce,
            responseHash,
            uint16(_chunkCount(responseBody.length)),
            uint32(responseBody.length)
        );
        if (_ladderOn(nonce, true)) {
            _ladderCost(nonce, true, g0,
                abi.encodeWithSelector(msg.sig, nonce, idempotencyKey, request, responseBody, receipt, receiptSignature));
        }
    }

    function beginBuyerPublication(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        uint32 totalBytes,
        uint16 chunkCount
    ) external onlyDelegateCall {
        uint256 g0 = gasleft();
        _buyerPublicationAccess(nonce);
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        if (totalBytes > profile.maxResponseBytes) revert ResponseTooLarge();
        bool measured = _ladderOn(nonce, true);
        if (measured && buyerPublications[nonce].chunkCount != 0) revert InvalidPublication();
        if (chunkCount != _chunkCount(totalBytes)) revert InvalidPublication();
        _validatePublishedRequest(purchase, nonce, idempotencyKey, request, profile.maxRequestBytes);
        _validateReceipt(purchase, nonce, receipt, receiptSignature);
        Publication storage publication = buyerPublications[nonce];
        delete publication.chunkHashes;
        buyerRecoveries[nonce].publishedChunks = 0;
        publication.responseHash = receipt.responseHash;
        publication.totalBytes = totalBytes;
        publication.bytesWritten = 0;
        publication.chunkCount = chunkCount;
        for (uint256 i; i < chunkCount; i++) {
            publication.chunkHashes.push(bytes32(0));
        }
        emit PublicationStarted(nonce, receipt.responseHash, chunkCount, totalBytes);
        if (measured) {
            _ladderCost(nonce, true, g0, abi.encodeWithSelector(
                msg.sig, nonce, idempotencyKey, request, receipt, receiptSignature, totalBytes, chunkCount));
        }
    }

    function publishBuyerChunk(bytes32 nonce, uint16 index, bytes calldata chunk)
        external
        onlyDelegateCall
    {
        uint256 g0 = gasleft();
        _buyerPublicationAccess(nonce);
        Publication storage publication = buyerPublications[nonce];
        if (publication.chunkCount == 0 || index >= publication.chunkCount) {
            revert InvalidPublication();
        }
        if (index != buyerRecoveries[nonce].publishedChunks) revert InvalidPublication();
        if (publication.chunkHashes[index] != bytes32(0)) revert InvalidPublication();
        uint256 expected = RESPONSE_CHUNK_BYTES;
        if (index + 1 == publication.chunkCount) {
            expected = publication.totalBytes - uint256(index) * RESPONSE_CHUNK_BYTES;
        }
        if (chunk.length != expected) revert InvalidPublication();
        publication.chunkHashes[index] = keccak256(chunk);
        publication.bytesWritten += uint32(chunk.length);
        buyerRecoveries[nonce].publishedChunks++;
        emit PublicationChunk(nonce, index, uint32(chunk.length));
        if (_ladderOn(nonce, true)) _ladderCost(nonce, true, g0, abi.encodeWithSelector(msg.sig, nonce, index, chunk));
    }

    function finalizeBuyerPublication(bytes32 nonce) external onlyDelegateCall nonReentrant {
        uint256 g0 = gasleft();
        _buyerPublicationAccess(nonce);
        Publication storage publication = buyerPublications[nonce];
        if (
            publication.chunkCount == 0 || publication.bytesWritten != publication.totalBytes
                || buyerRecoveries[nonce].publishedChunks != publication.chunkCount
        ) revert InvalidPublication();
        bytes32 responseHash = _responseRoot(publication.chunkHashes);
        if (responseHash != publication.responseHash) revert InvalidPublication();
        _finishBuyerPublication(nonce, responseHash, publication.chunkCount, publication.totalBytes);
        if (_ladderOn(nonce, true)) _ladderCost(nonce, true, g0, abi.encodeWithSelector(msg.sig, nonce));
    }
}
