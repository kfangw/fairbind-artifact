// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Proof check of a verifiable random function (ADR 0031). A deployment
/// fixes the verifier and the provider's public key in the adapter; the
/// adapter accepts an output only when this check passes for the stored
/// input. A verifier for a scheme with unique outputs (one valid output per
/// key and input) makes the value independent of who delivers it.
interface IVrfVerifier {
    function verify(bytes calldata publicKey, bytes calldata alpha, bytes32 output, bytes calldata proof)
        external
        view
        returns (bool);
}
