// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

struct VrfRequest {
    bytes32 keyHash;
    uint256 subId;
    uint16 requestConfirmations;
    uint32 callbackGasLimit;
    uint32 numWords;
    bytes extraArgs;
}

interface IVrfCoordinatorV25 {
    function requestRandomWords(VrfRequest calldata req) external returns (uint256 requestId);
}

/// The sample-value path of the settlement contract over Chainlink VRF v2.5,
/// for the fulfillment gas on a Base fork: each request is for a new
/// (profile, epoch) key, recorded against the request id; the callback
/// checks the caller, reads the key, takes the first value only and writes
/// it to a new slot, as the settlement contract's sample value does once per
/// profile epoch. The request and callback interface is the G10d minimal
/// consumer's (request(bool,uint32), lastWord(), WordStored), so the G10d
/// fulfillment script drives it unchanged.
contract SettlementVrfConsumer {
    bytes4 private constant EXTRA_ARGS_V1_TAG = bytes4(keccak256("VRF ExtraArgsV1"));
    address public immutable coordinator;
    bytes32 public immutable keyHash;
    uint256 public immutable subId;
    uint256 public lastRequestId;
    uint256 public epochs;
    mapping(uint256 => bytes32) public keyOf; // request id => (profile, epoch)
    mapping(bytes32 => uint256) public sampleValue;

    event WordStored(uint256 indexed requestId, uint256 word);

    error OnlyCoordinator(address have);

    constructor(address coordinator_, bytes32 keyHash_, uint256 subId_) {
        coordinator = coordinator_;
        keyHash = keyHash_;
        subId = subId_;
    }

    function request(bool nativePayment, uint32 callbackGasLimit) external returns (uint256 id) {
        id = IVrfCoordinatorV25(coordinator).requestRandomWords(
            VrfRequest({
                keyHash: keyHash,
                subId: subId,
                requestConfirmations: 0,
                callbackGasLimit: callbackGasLimit,
                numWords: 1,
                extraArgs: abi.encodeWithSelector(EXTRA_ARGS_V1_TAG, nativePayment)
            })
        );
        keyOf[id] = keccak256(abi.encode(bytes32("profile"), ++epochs));
        lastRequestId = id;
    }

    function rawFulfillRandomWords(uint256 requestId, uint256[] calldata randomWords) external {
        if (msg.sender != coordinator) revert OnlyCoordinator(msg.sender);
        bytes32 k = keyOf[requestId];
        if (k == 0 || sampleValue[k] != 0) return;
        sampleValue[k] = randomWords[0];
        emit WordStored(requestId, randomWords[0]);
    }

    function lastWord() external view returns (uint256) {
        return sampleValue[keyOf[lastRequestId]];
    }
}
