// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// ECVRF on secp256k1 with keccak256, verified on-chain in the style of
/// Chainlink's VRF.sol (the verifier inside the VRF v2 and v2.5
/// coordinators): try-and-increment hash to curve with the square root taken
/// by the modexp precompile, the two scalar products c*Gamma and s*H and the
/// combination c*pk + s*G checked with the ecrecover trick, and one field
/// inverse supplied by the prover for the affine sum V = c*Gamma + s*H.
/// It is a measurement sketch, not an audited verifier, and its encoding is
/// not byte-compatible with VRF.sol (VRF.sol takes a projective sum and zInv;
/// here the prover supplies the affine inverse instead).
///
/// Statement: Gamma = sk*H(pk, alpha); proof (Gamma, c, s) with
/// U = c*pk + s*G, V = c*Gamma + s*H, c = H2(H, pk, Gamma, V, addr(U)) mod n,
/// output beta = keccak(3, Gamma). The prover sets s = m - c*sk mod n.
library EcVrf {
    uint256 internal constant P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F;
    uint256 internal constant N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    uint256 internal constant GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798;
    uint256 internal constant GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8;
    uint256 internal constant SQRT_EXP = (P + 1) / 4;

    struct Proof {
        uint256[2] gamma;
        uint256 c;
        uint256 s;
        address uWitness; // address of U = c*pk + s*G
        uint256[2] cGammaWitness; // c*Gamma
        uint256[2] sHashWitness; // s*H
        uint256 inv; // (sHashWitness.x - cGammaWitness.x)^-1 mod p
    }

    error BadPoint();
    error BadProof(uint256 step);

    function onCurve(uint256[2] memory q) internal pure returns (bool) {
        if (q[0] == 0 || q[0] >= P || q[1] >= P) return false;
        return mulmod(q[1], q[1], P) == addmod(mulmod(mulmod(q[0], q[0], P), q[0], P), 7, P);
    }

    function modexp(uint256 b, uint256 e, uint256 m) internal view returns (uint256 r) {
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, 0x20)
            mstore(add(p, 0x20), 0x20)
            mstore(add(p, 0x40), 0x20)
            mstore(add(p, 0x60), b)
            mstore(add(p, 0x80), e)
            mstore(add(p, 0xa0), m)
            if iszero(staticcall(gas(), 0x05, p, 0xc0, p, 0x20)) { revert(0, 0) }
            r := mload(p)
        }
    }

    /// Try-and-increment: x0 = keccak(1, pk, alpha) mod p, then x = keccak(x)
    /// mod p until x^3 + 7 is a square; the even root is taken.
    function hashToCurve(uint256[2] memory pk, bytes32 alpha) internal view returns (uint256[2] memory h) {
        uint256 x = uint256(keccak256(abi.encodePacked(uint256(1), pk[0], pk[1], alpha))) % P;
        while (true) {
            uint256 y2 = addmod(mulmod(mulmod(x, x, P), x, P), 7, P);
            uint256 y = modexp(y2, SQRT_EXP, P);
            if (mulmod(y, y, P) == y2) {
                if (y & 1 == 1) y = P - y;
                h[0] = x;
                h[1] = y;
                return h;
            }
            x = uint256(keccak256(abi.encodePacked(x))) % P;
        }
    }

    function addrOf(uint256[2] memory q) internal pure returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked(q[0], q[1])))));
    }

    /// scalar * m == product, by ecrecover(0, v(m), m.x, scalar * m.x).
    function ecmulVerify(uint256[2] memory m, uint256 scalar, uint256[2] memory product) internal pure returns (bool) {
        if (scalar == 0 || m[0] >= N) return false;
        uint8 v = m[1] & 1 == 0 ? 27 : 28;
        address a = ecrecover(bytes32(0), v, bytes32(m[0]), bytes32(mulmod(scalar, m[0], N)));
        return a != address(0) && a == addrOf(product);
    }

    /// c * p + s * G has address w, by ecrecover(-s * p.x, v(p), p.x, c * p.x).
    function linComboWithGen(uint256 c, uint256[2] memory p, uint256 s, address w) internal pure returns (bool) {
        if (w == address(0) || p[0] >= N) return false;
        uint8 v = p[1] & 1 == 0 ? 27 : 28;
        bytes32 h = bytes32(N - mulmod(p[0], s, N));
        address a = ecrecover(h, v, bytes32(p[0]), bytes32(mulmod(c, p[0], N)));
        return a == w;
    }

    function challenge(
        uint256[2] memory h,
        uint256[2] memory pk,
        uint256[2] memory gamma,
        uint256 vx,
        uint256 vy,
        address u
    ) internal pure returns (uint256) {
        return uint256(keccak256(abi.encodePacked(uint256(2), h[0], h[1], pk[0], pk[1], gamma[0], gamma[1], vx, vy, u))) % N;
    }

    /// Verifies the proof for (pk, alpha) and returns beta. pk is assumed on
    /// the curve (checked once when the key is fixed at deployment).
    function verify(uint256[2] memory pk, bytes32 alpha, Proof memory pr) internal view returns (uint256 beta) {
        if (!onCurve(pr.gamma) || !onCurve(pr.cGammaWitness) || !onCurve(pr.sHashWitness)) revert BadPoint();
        if (!linComboWithGen(pr.c, pk, pr.s, pr.uWitness)) revert BadProof(1);
        uint256[2] memory h = hashToCurve(pk, alpha);
        if (!ecmulVerify(pr.gamma, pr.c, pr.cGammaWitness)) revert BadProof(2);
        if (!ecmulVerify(h, pr.s, pr.sHashWitness)) revert BadProof(3);
        uint256 x1 = pr.cGammaWitness[0];
        uint256 y1 = pr.cGammaWitness[1];
        uint256 x2 = pr.sHashWitness[0];
        if (mulmod(addmod(x2, P - x1, P), pr.inv, P) != 1) revert BadProof(4);
        uint256 lam = mulmod(addmod(pr.sHashWitness[1], P - y1, P), pr.inv, P);
        uint256 vx = addmod(mulmod(lam, lam, P), P - addmod(x1, x2, P), P);
        uint256 vy = addmod(mulmod(lam, addmod(x1, P - vx, P), P), P - y1, P);
        if (challenge(h, pk, pr.gamma, vx, vy, pr.uWitness) != pr.c) revert BadProof(5);
        beta = uint256(keccak256(abi.encodePacked(uint256(3), pr.gamma[0], pr.gamma[1])));
    }
}

/// Test-side prover (Jacobian scalar multiplication). Gas does not matter here.
library EcVrfProver {
    uint256 internal constant P = EcVrf.P;
    uint256 internal constant N = EcVrf.N;

    function _double(uint256 x, uint256 y, uint256 z) private pure returns (uint256, uint256, uint256) {
        if (y == 0) return (0, 0, 0);
        uint256 a = mulmod(x, x, P);
        uint256 b = mulmod(y, y, P);
        uint256 c = mulmod(b, b, P);
        uint256 t = addmod(x, b, P);
        uint256 d = mulmod(2, addmod(mulmod(t, t, P), P - addmod(a, c, P), P), P);
        uint256 e = mulmod(3, a, P);
        uint256 f = mulmod(e, e, P);
        uint256 x3 = addmod(f, P - mulmod(2, d, P), P);
        uint256 y3 = addmod(mulmod(e, addmod(d, P - x3, P), P), P - mulmod(8, c, P), P);
        uint256 z3 = mulmod(mulmod(2, y, P), z, P);
        return (x3, y3, z3);
    }

    /// (x1, y1, z1) + affine (x2, y2); z1 != 0 and the points are distinct and not inverse.
    function _addMixed(uint256 x1, uint256 y1, uint256 z1, uint256 x2, uint256 y2)
        private
        pure
        returns (uint256, uint256, uint256)
    {
        uint256 z1z1 = mulmod(z1, z1, P);
        uint256 u2 = mulmod(x2, z1z1, P);
        uint256 s2 = mulmod(mulmod(y2, z1, P), z1z1, P);
        uint256 h = addmod(u2, P - x1, P);
        require(h != 0, "degenerate add");
        uint256 hh = mulmod(h, h, P);
        uint256 i = mulmod(4, hh, P);
        uint256 j = mulmod(h, i, P);
        uint256 r = mulmod(2, addmod(s2, P - y1, P), P);
        uint256 v = mulmod(x1, i, P);
        uint256 x3 = addmod(addmod(mulmod(r, r, P), P - j, P), P - mulmod(2, v, P), P);
        uint256 y3 = addmod(mulmod(r, addmod(v, P - x3, P), P), P - mulmod(mulmod(2, y1, P), j, P), P);
        uint256 t = addmod(z1, h, P);
        uint256 z3 = addmod(mulmod(t, t, P), P - addmod(z1z1, hh, P), P);
        return (x3, y3, z3);
    }

    function mul(uint256 k, uint256[2] memory q) internal view returns (uint256[2] memory out) {
        k %= N;
        require(k != 0, "zero scalar");
        uint256 bit = 255;
        while ((k >> bit) & 1 == 0) bit--;
        (uint256 x, uint256 y, uint256 z) = (q[0], q[1], 1);
        while (bit > 0) {
            bit--;
            (x, y, z) = _double(x, y, z);
            if ((k >> bit) & 1 == 1) (x, y, z) = _addMixed(x, y, z, q[0], q[1]);
        }
        uint256 zi = EcVrf.modexp(z, P - 2, P);
        uint256 zi2 = mulmod(zi, zi, P);
        out[0] = mulmod(x, zi2, P);
        out[1] = mulmod(y, mulmod(zi2, zi, P), P);
    }

    function publicKey(uint256 sk) internal view returns (uint256[2] memory) {
        return mul(sk, [EcVrf.GX, EcVrf.GY]);
    }

    /// uAddr is the address of m*G (vm.addr(m) gives it without a scalar product).
    function prove(uint256 sk, uint256[2] memory pk, bytes32 alpha, uint256 m, address uAddr)
        internal
        view
        returns (EcVrf.Proof memory pr)
    {
        uint256[2] memory h = EcVrf.hashToCurve(pk, alpha);
        pr.gamma = mul(sk, h);
        uint256[2] memory v = mul(m, h);
        pr.uWitness = uAddr;
        pr.c = EcVrf.challenge(h, pk, pr.gamma, v[0], v[1], uAddr);
        pr.s = addmod(m % N, N - mulmod(pr.c, sk, N), N);
        pr.cGammaWitness = mul(pr.c, pr.gamma);
        pr.sHashWitness = mul(pr.s, h);
        pr.inv = EcVrf.modexp(addmod(pr.sHashWitness[0], P - pr.cGammaWitness[0], P), P - 2, P);
    }
}
