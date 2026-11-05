// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Request struct of VRFV2PlusClient.RandomWordsRequest (Chainlink VRF v2.5).
struct RandomWordsRequest {
    bytes32 keyHash;
    uint256 subId;
    uint16 requestConfirmations;
    uint32 callbackGasLimit;
    uint32 numWords;
    bytes extraArgs;
}

interface IVrfCoordinatorV2Plus {
    function requestRandomWords(RandomWordsRequest calldata req) external returns (uint256 requestId);
}

/// Minimal VRF v2.5 consumer for the G10d cost measurement on a Base fork:
/// one request for one word, and a callback that checks the caller, stores
/// the word and emits an event (the least a FairBind sample-value acceptance
/// does once the coordinator has verified the proof).
contract MinimalVrfConsumer {
    bytes4 private constant EXTRA_ARGS_V1_TAG = bytes4(keccak256("VRF ExtraArgsV1"));
    address public immutable coordinator;
    bytes32 public immutable keyHash;
    uint256 public immutable subId;
    uint256 public lastRequestId;
    uint256 public lastWord;

    event WordStored(uint256 indexed requestId, uint256 word);

    error OnlyCoordinator(address have);

    constructor(address coordinator_, bytes32 keyHash_, uint256 subId_) {
        coordinator = coordinator_;
        keyHash = keyHash_;
        subId = subId_;
    }

    function request(bool nativePayment, uint32 callbackGasLimit) external returns (uint256 id) {
        id = IVrfCoordinatorV2Plus(coordinator).requestRandomWords(
            RandomWordsRequest({
                keyHash: keyHash,
                subId: subId,
                requestConfirmations: 0,
                callbackGasLimit: callbackGasLimit,
                numWords: 1,
                extraArgs: abi.encodeWithSelector(EXTRA_ARGS_V1_TAG, nativePayment)
            })
        );
        lastRequestId = id;
    }

    /// Called by the coordinator through _callWithExactGas.
    function rawFulfillRandomWords(uint256 requestId, uint256[] calldata randomWords) external {
        if (msg.sender != coordinator) revert OnlyCoordinator(msg.sender);
        lastWord = randomWords[0];
        emit WordStored(requestId, randomWords[0]);
    }
}
