#!/usr/bin/env python3
"""Builds SyntheticHistoryFixture.sol (and a JSON copy): tier 0 material for
the fixed P5StorageVerifier, built without a node.

The state holds the EIP-2935 history account whose storage ring keeps the
hashes of a chain of synthetic block headers (block b has timestamp
T0 + 2 b and parent hash = hash of block b - 1). The anchored header (block
NUM) carries the root of that state. The fixture gives, for each case, the
reference block, its header and the next block's header, and the account
and storage proofs for the next block's slot:

  N  (normal)       reference block REF_N, next block REF_N + 1 in the ring
  Z  (leading zero) the next block's hash starts with a zero byte (the
                    header's extra-data field is ground until it does)
  L  (last)         reference block NUM - 1, next block = the anchored block
  E  (empty slot)   a storage proof for a slot that is absent from the ring

Only the header fields the contract reads are meaningful (parent hash 0,
state root 3, number 8, timestamp 11); the others are fixed filler. The
trie proofs are those of eth_getProof (RLP-encoded nodes from the root).

usage: gen_synthetic_fixture.py <out .sol> <out .json>
needs: pip install rlp trie "eth-hash[pycryptodome]"
"""
import json, sys

import rlp
from eth_hash.auto import keccak
from trie import HexaryTrie

HISTORY = bytes.fromhex("0000F90827F1C53a10cb7A02335B175320002935")
WINDOW = 8191
NUM = 8392
T0 = 1_792_734_218  # block REF_N has timestamp 1_792_743_000 (SdkBase.VALID_AFTER)
REF_N = 4391
REF_E_NEXT = 6001  # the slot of this block is left out of the ring


def header(parent, number, state_root=b"\x00" * 32, extra=b""):
    return rlp.encode([
        parent, keccak(rlp.encode([])), b"\x00" * 20, state_root, b"\x11" * 32, b"\x22" * 32, b"\x00" * 256,
        0, number, 30_000_000, 21_000, T0 + 2 * number, extra, b"\x33" * 32, b"\x00" * 8, 1_000_000_000,
    ])


def strip(h):
    return h.lstrip(b"\x00")


def main():
    out_sol, out_json = sys.argv[1], sys.argv[2]
    # chain of headers 0..NUM-1 (only hashes are kept; headers of the cases are kept whole)
    hashes, keep = {}, {}
    parent = b"\x00" * 32
    z_next = None
    for b in range(NUM):
        extra = b""
        if b > REF_N + 1 and z_next is None and b < NUM - 2:
            # grind block b so that its hash starts with a zero byte
            i = 0
            while True:
                extra = i.to_bytes(4, "big")
                if keccak(header(parent, b, extra=extra))[0] == 0:
                    break
                i += 1
            z_next = b
        h = header(parent, b, extra=extra)
        hashes[b] = keccak(h)
        if b in (REF_N, REF_N + 1, NUM - 1) or (z_next is not None and b in (z_next - 1, z_next)):
            keep[b] = h
        parent = hashes[b]
    # header z_next - 1 was produced before z_next was known: rebuild it
    keep[z_next - 1] = header(hashes[z_next - 2], z_next - 1)
    assert keccak(keep[z_next - 1]) == hashes[z_next - 1]
    # EIP-2935 ring after block NUM: slots of blocks NUM - WINDOW .. NUM - 1
    st = HexaryTrie(db={})
    for b in range(NUM - WINDOW, NUM):
        if b == REF_E_NEXT:
            continue
        st[keccak((b % WINDOW).to_bytes(32, "big"))] = rlp.encode(strip(hashes[b]))
    acct = rlp.encode([1, 0, st.root_hash, keccak(b"history code")])
    at = HexaryTrie(db={})
    at[keccak(HISTORY)] = acct
    for i in range(1, 40):  # other accounts
        at[keccak(i.to_bytes(20, "big"))] = rlp.encode([i, 10**18 * i, keccak(rlp.encode(b"")), keccak(b"")])
    anchored = header(hashes[NUM - 1], NUM, state_root=at.root_hash)
    proof = lambda t, k: ["0x" + rlp.encode(n).hex() for n in t.get_proof(k)]
    ap = proof(at, keccak(HISTORY))
    sp = lambda b: proof(st, keccak((b % WINDOW).to_bytes(32, "big")))
    zh = hashes[z_next]
    assert zh[0] == 0 and len(strip(zh)) < 32
    d = {
        "BLOCK_HASH": "0x" + keccak(anchored).hex(), "BLOCK_NUMBER": NUM, "T0": T0, "header": "0x" + anchored.hex(),
        "accountProof": ap,
        "N": {"REF": REF_N, "REF_HASH": "0x" + hashes[REF_N].hex(), "refHeader": "0x" + keep[REF_N].hex(),
              "nextHeader": "0x" + keep[REF_N + 1].hex(), "storageProof": sp(REF_N + 1),
              "NEXT_HASH": "0x" + hashes[REF_N + 1].hex()},
        "Z": {"REF": z_next - 1, "REF_HASH": "0x" + hashes[z_next - 1].hex(), "refHeader": "0x" + keep[z_next - 1].hex(),
              "nextHeader": "0x" + keep[z_next].hex(), "storageProof": sp(z_next), "NEXT_HASH": "0x" + zh.hex()},
        "L": {"REF": NUM - 1, "REF_HASH": "0x" + hashes[NUM - 1].hex(), "refHeader": "0x" + keep[NUM - 1].hex(),
              "nextHeader": "0x" + anchored.hex(), "storageProof": []},
        "E": {"NEXT": REF_E_NEXT, "storageProof": sp(REF_E_NEXT)},
    }
    json.dump(d, open(out_json, "w"), indent=1)

    def arr(name, xs):
        s = f"    function {name}() internal pure returns (bytes[] memory p) {{\n        p = new bytes[]({len(xs)});\n"
        for i, x in enumerate(xs):
            s += f'        p[{i}] = hex"{x[2:]}";\n'
        return s + "    }\n"

    def by(name, x):
        return f'    function {name}() internal pure returns (bytes memory) {{\n        return hex"{x[2:]}";\n    }}\n'

    sol = ["// SPDX-License-Identifier: MIT", "pragma solidity ^0.8.24;", "",
           "/// Generated by gen_synthetic_fixture.py (synthetic chain and state, no node).",
           "library SyntheticHistoryFixture {",
           f"    bytes32 internal constant BLOCK_HASH = {d['BLOCK_HASH']};",
           f"    uint256 internal constant BLOCK_NUMBER = {NUM};",
           f"    uint256 internal constant T0 = {T0};"]
    for c in "NZL":
        sol.append(f"    uint256 internal constant {c}_REF = {d[c]['REF']};")
        sol.append(f"    bytes32 internal constant {c}_REF_HASH = {d[c]['REF_HASH']};")
    sol.append(f"    bytes32 internal constant N_NEXT_HASH = {d['N']['NEXT_HASH']};")
    sol.append(f"    bytes32 internal constant Z_NEXT_HASH = {d['Z']['NEXT_HASH']};")
    sol.append(f"    uint256 internal constant E_NEXT = {REF_E_NEXT};")
    body = by("header", d["header"]) + arr("accountProof", ap)
    for c in "NZL":
        body += by(f"{c.lower()}RefHeader", d[c]["refHeader"]) + by(f"{c.lower()}NextHeader", d[c]["nextHeader"])
        body += arr(f"{c.lower()}StorageProof", d[c]["storageProof"])
    body += arr("eStorageProof", d["E"]["storageProof"])
    open(out_sol, "w").write("\n".join(sol) + "\n\n" + body + "}\n")


if __name__ == "__main__":
    main()
