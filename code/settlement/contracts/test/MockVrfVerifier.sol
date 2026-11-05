// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfVerifier } from "../src/randomness/IVrfVerifier.sol";

/// Test stand-in for a VRF proof check. The public key is abi.encode(signer);
/// a proof is the signer's 65-byte low-s ECDSA signature over keccak256(alpha)
/// and the output is keccak256(abi.encode(OUTPUT_DOMAIN, proof)). It checks
/// the binding of output, proof, key and input, not the uniqueness of a real
/// VRF; the adapter keeps the first stored output of a request.
contract MockVrfVerifier is IVrfVerifier {
    bytes32 public constant OUTPUT_DOMAIN = keccak256("mock-vrf/output/v1");
    uint256 internal constant HALF_N = 0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    function verify(bytes calldata publicKey, bytes calldata alpha, bytes32 output, bytes calldata proof)
        external
        pure
        override
        returns (bool)
    {
        if (publicKey.length != 32 || proof.length != 65) return false;
        address signer = abi.decode(publicKey, (address));
        bytes32 r = bytes32(proof[0:32]);
        bytes32 s = bytes32(proof[32:64]);
        uint8 v = uint8(proof[64]);
        if (uint256(s) > HALF_N || (v != 27 && v != 28)) return false;
        address got = ecrecover(keccak256(alpha), v, r, s);
        return got != address(0) && got == signer && output == keccak256(abi.encode(OUTPUT_DOMAIN, proof));
    }
}
