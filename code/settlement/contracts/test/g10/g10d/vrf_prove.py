#!/usr/bin/env python3
"""ECVRF prover byte-compatible with Chainlink VRF.sol (VRF v2.5 coordinator).

Port of the verifier in src/v0.8/vrf/VRF.sol (the source verified on Sourcify
for the Base coordinator 0xd5D5...F634): secp256k1, keccak256,
try-and-increment hash to curve with prefix 1, challenge with prefix 2, the
witnesses the verifier expects (uWitness = address(k*G), c*Gamma, s*H, and
zInv = 1/z of VRF.sol's projective sum). Used on a local fork only, with a
throwaway key registered there by impersonating the coordinator owner.

  vrf_prove.py pubkey --key KEYFILE           -> "x y" of the public key
  vrf_prove.py prove --key KEYFILE --preseed N --blockhash H
                                              -> JSON proof tuple fields
The secret key is read from KEYFILE (hex) and never printed.
"""
import argparse
import json
import secrets


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = _ROT[x][y]
                b[y][(2 * x + 3 * y) % 5] = ((a[x][y] << r) | (a[x][y] >> (64 - r))) & _M if r else a[x][y]
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def k256(data):
    """Keccak-256 (the Ethereum hash, pad 0x01), pure Python."""
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        a = _f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


def u256(x):
    return x.to_bytes(32, "big")


def add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % P == 0:
            return None
        lam = 3 * p[0] * p[0] * pow(2 * p[1], -1, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return (x, (lam * (p[0] - x) - p[1]) % P)


def mul(k, p):
    r = None
    while k:
        if k & 1:
            r = add(r, p)
        p = add(p, p)
        k >>= 1
    return r


def ysq(x):
    return (x * x * x + 7) % P


def field_hash(b):
    x = int.from_bytes(k256(b), "big")
    while x >= P:
        x = int.from_bytes(k256(u256(x)), "big")
    return x


def candidate(b):
    x = field_hash(b)
    y = pow(ysq(x), (P + 1) // 4, P)
    if y % 2 == 1:
        y = P - y
    return (x, y)


def on_curve(p):
    return ysq(p[0]) == p[1] * p[1] % P


def hash_to_curve(pk, seed, tries=None):
    rv = candidate(u256(1) + u256(pk[0]) + u256(pk[1]) + u256(seed))
    n = 1
    while not on_curve(rv):
        rv = candidate(u256(rv[0]))
        n += 1
    if tries is not None:
        tries.append(n)
    return rv


def addr(p):
    return k256(u256(p[0]) + u256(p[1]))[12:]


def psub(x1, z1, x2, z2):
    return ((z2 * x1 + (P - x2) * z1) % P, z1 * z2 % P)


def pmul(x1, z1, x2, z2):
    return (x1 * x2 % P, z1 * z2 % P)


def projective_ec_add(p, q):
    px, py = p
    qx, qy = q
    z1 = z2 = 1
    lx = (qy + P - py) % P
    lz = (qx + P - px) % P
    sx, dx = pmul(lx, lz, lx, lz)
    sx, dx = psub(sx, dx, px, z1)
    sx, dx = psub(sx, dx, qx, z2)
    sy, dy = psub(px, z1, sx, dx)
    sy, dy = pmul(sy, dy, lx, lz)
    sy, dy = psub(sy, dy, py, z1)
    if dx != dy:
        sx = sx * dy % P
        sy = sy * dx % P
        sz = dx * dy % P
    else:
        sz = dx
    return sx, sy, sz


def read_key(path):
    return int(open(path).read().strip(), 16) % N


def prove(sk, preseed, blockhash):
    pk = mul(sk, G)
    seed = int.from_bytes(k256(u256(preseed) + u256(blockhash)), "big")  # coordinator's actualSeed
    tries = []
    h = hash_to_curve(pk, seed, tries)
    gamma = mul(sk, h)
    while True:
        k = secrets.randbelow(N - 1) + 1
        u = mul(k, G)
        v = mul(k, h)
        uw = addr(u)
        c = int.from_bytes(k256(u256(2) + u256(h[0]) + u256(h[1]) + u256(pk[0]) + u256(pk[1]) + u256(gamma[0])
                                + u256(gamma[1]) + u256(v[0]) + u256(v[1]) + uw), "big")
        s = (k - c * sk) % N
        if s == 0 or c % N == 0:
            continue
        cg = mul(c, gamma)
        sh = mul(s, h)
        if cg[0] == sh[0]:
            continue
        x, y, z = projective_ec_add(cg, sh)
        zinv = pow(z, -1, P)
        assert (x * zinv % P, y * zinv % P) == v
        return {"pk": [pk[0], pk[1]], "gamma": [gamma[0], gamma[1]], "c": c, "s": s, "seed": preseed,
                "uWitness": "0x" + uw.hex(), "cGammaWitness": [cg[0], cg[1]], "sHashWitness": [sh[0], sh[1]],
                "zInv": zinv, "h2c_tries": tries[0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pubkey", "prove"])
    ap.add_argument("--key", required=True)
    ap.add_argument("--preseed")
    ap.add_argument("--blockhash")
    a = ap.parse_args()
    sk = read_key(a.key)
    if a.cmd == "pubkey":
        pk = mul(sk, G)
        print(pk[0], pk[1])
    else:
        print(json.dumps(prove(sk, int(a.preseed, 0), int(a.blockhash, 16))))


if __name__ == "__main__":
    main()
