// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IRandomness } from "./IRandomness.sol";

/// Request-based randomness behind IRandomness (design 2 rule D2-23, ADR
/// 0031). Values are fixed per request, not per round: a request is
/// identified by (kind, input), and its VRF input alpha is
/// abi.encode(DOMAIN, chain id, consumer, kind, input), built and stored at
/// the first request. A block hash never enters alpha. Only the consumer
/// contract named at deployment may request, so the provider answers only
/// requests the consumer registered under its own rules. A repeated request
/// of the same id keeps the stored alpha and only asks again.
///
/// A response carries the output and its proof; the adapter stores the
/// output only after the proof checks against the fixed public key, and only
/// in a block at or before the request's deadline when it has one. A later
/// response is refused, so no value ever exists for a request past its
/// deadline. The consumer reads values with valueOf(id).
interface IVrfRandomness is IRandomness {
    /// Profile bound D_V on the response delay, in blocks after the request.
    function responseBlocks() external view returns (uint32);

    /// Slack T_V after the normal response bound before a deadline passes.
    function deadlineSlackBlocks() external view returns (uint32);

    /// Registers request `id` = keccak256(abi.encode(kind, input)) and asks
    /// the provider for its value; consumer only. The first request stores
    /// alpha and the deadline (zero for none); a repeated request emits the
    /// stored alpha again and changes nothing.
    function request(uint8 kind, bytes calldata input, uint64 deadline) external returns (bytes32 id);

    /// The value of request `id`, or ready = false while none is stored.
    function valueOf(bytes32 id) external view returns (bool ready, bytes32 value);

    /// Block of the first request, block in which the value was stored (zero
    /// while none is), and the deadline of request `id`.
    function requestTimes(bytes32 id) external view returns (uint64 requested, uint64 delivered, uint64 deadline);
}
