// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfRandomness } from "./IVrfRandomness.sol";
import { IVrfVerifier } from "./IVrfVerifier.sol";

/// VRF adapter for the sampling, assignment and auxiliary values (design 2
/// rule D2-23, ADR 0031). The consumer, the proof verifier, the provider's
/// public key and the two delay bounds are fixed at deployment.
contract FairBindVrf is IVrfRandomness {
    string public constant DOMAIN = "FairBind/vrf/v1";

    address public immutable consumer;
    IVrfVerifier public immutable verifier;
    uint32 public immutable override responseBlocks;
    uint32 public immutable override deadlineSlackBlocks;
    bytes public publicKey;

    struct Request {
        uint64 requested;
        uint64 delivered;
        uint64 deadline;
        bytes32 value;
        bytes alpha;
    }

    mapping(bytes32 => Request) internal requests;

    event RandomnessRequested(bytes32 indexed id, uint8 indexed kind, bytes alpha, uint64 deadline);
    event RandomnessDelivered(bytes32 indexed id, bytes32 value);

    error Unauthorized();
    error UnknownRequest();
    error DeadlinePassed();
    error AlreadyDelivered();
    error InvalidProof();
    error InvalidConfiguration();

    constructor(
        address consumer_,
        IVrfVerifier verifier_,
        bytes memory publicKey_,
        uint32 responseBlocks_,
        uint32 deadlineSlackBlocks_
    ) {
        if (consumer_ == address(0) || address(verifier_).code.length == 0 || publicKey_.length == 0) {
            revert InvalidConfiguration();
        }
        consumer = consumer_;
        verifier = verifier_;
        publicKey = publicKey_;
        responseBlocks = responseBlocks_;
        deadlineSlackBlocks = deadlineSlackBlocks_;
    }

    /// D_S = D_V + 1: the sampling value is due D_V blocks after a request
    /// made in the first block after the anchor deadline.
    function delayBlocks() external view override returns (uint32) {
        return responseBlocks + 1;
    }

    /// Round values do not exist for a request-based source; the consumer
    /// reads valueOf(bytes32).
    function valueOf(uint64) external pure override returns (bool ready, bytes32 value) {
        return (false, bytes32(0));
    }

    /// The VRF input of request (kind, input) for this consumer and chain.
    function alphaOf(uint8 kind, bytes calldata input) external view returns (bytes memory) {
        return _alpha(kind, input);
    }

    /// Every production build: the domain, the chain id, the consumer, the
    /// kind and the input, and no block hash. A mutation build of the tests
    /// overrides it.
    function _alpha(uint8 kind, bytes calldata input) internal view virtual returns (bytes memory) {
        return abi.encode(DOMAIN, block.chainid, consumer, kind, input);
    }

    /// Whether a response in this block comes too late for a request with
    /// this deadline. A mutation build of the tests accepts every response.
    function _late(uint64 deadline) internal view virtual returns (bool) {
        return deadline != 0 && block.number > deadline;
    }

    function request(uint8 kind, bytes calldata input, uint64 deadline) external override returns (bytes32 id) {
        if (msg.sender != consumer) revert Unauthorized();
        id = keccak256(abi.encode(kind, input));
        Request storage r = requests[id];
        if (r.requested == 0) {
            r.requested = uint64(block.number);
            r.deadline = deadline;
            r.alpha = _alpha(kind, input);
        }
        emit RandomnessRequested(id, kind, r.alpha, r.deadline);
    }

    /// Stores the output of request `id` once its proof checks against the
    /// stored alpha and the fixed public key. Anyone may deliver it; the
    /// verifier's uniqueness makes the value the same for every deliverer.
    function fulfill(bytes32 id, bytes32 output, bytes calldata proof) external {
        Request storage r = requests[id];
        if (r.requested == 0) revert UnknownRequest();
        if (r.delivered != 0) revert AlreadyDelivered();
        if (_late(r.deadline)) revert DeadlinePassed();
        if (output == bytes32(0) || !verifier.verify(publicKey, r.alpha, output, proof)) revert InvalidProof();
        r.value = output;
        r.delivered = uint64(block.number);
        emit RandomnessDelivered(id, output);
    }

    function valueOf(bytes32 id) external view override returns (bool ready, bytes32 value) {
        Request storage r = requests[id];
        return (r.delivered != 0, r.value);
    }

    function requestTimes(bytes32 id) external view override returns (uint64 requested, uint64 delivered, uint64 deadline) {
        Request storage r = requests[id];
        return (r.requested, r.delivered, r.deadline);
    }

    /// The alpha stored at the first request of `id`, empty if none.
    function storedAlpha(bytes32 id) external view returns (bytes memory) {
        return requests[id].alpha;
    }
}
