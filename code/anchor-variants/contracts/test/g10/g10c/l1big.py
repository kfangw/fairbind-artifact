#!/usr/bin/env python3
"""L1 data fee of receipts rows whose calldata is too large for a cast
command-line argument (the large anchors of G10c-3).

Builds the EIP-1559 transaction of l1fee.py (chain 8453, nonce 7, the same
fee fields, gas limit = measured gas) in Python, with a stand-in signature
(yParity 1 and r, s from SHA-256 of the calldata, so incompressible like a
real signature), and applies the Fjord formula to its FastLZ size with the
fork-block inputs read from the header line of an l1fee.py output. No key and
no RPC. --check reruns rows that l1fee.py priced and reports the difference.

Usage: l1big.py --params L1FEE.tsv --out OUT.tsv [--check] IN.tsv...
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "g10b"))
from l1fee import flz_len, fjord_fee, calldata_stats, CHAIN_ID, NONCE, MAX_FEE, TIP  # noqa: E402


def rlp_bytes(b: bytes) -> bytes:
    if len(b) == 1 and b[0] < 0x80:
        return b
    return rlp_len(len(b), 0x80) + b


def rlp_len(n: int, off: int) -> bytes:
    if n < 56:
        return bytes([off + n])
    nb = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([off + 55 + len(nb)]) + nb


def rlp_int(i: int) -> bytes:
    return rlp_bytes(i.to_bytes((i.bit_length() + 7) // 8, "big") if i else b"")


def rlp_list(items) -> bytes:
    body = b"".join(items)
    return rlp_len(len(body), 0xC0) + body


def signed_tx(to: str, data: bytes, gas: int) -> bytes:
    h = hashlib.sha256(data).digest()
    r, s = h, hashlib.sha256(h).digest()
    fields = [rlp_int(CHAIN_ID), rlp_int(NONCE), rlp_int(TIP), rlp_int(MAX_FEE), rlp_int(gas),
              rlp_bytes(bytes.fromhex(to[2:])), rlp_int(0), rlp_bytes(data), rlp_list([]),
              rlp_int(1), rlp_bytes(r.lstrip(b"\0")), rlp_bytes(s.lstrip(b"\0"))]
    return b"\x02" + rlp_list(fields)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("tsv", nargs="+")
    a = ap.parse_args()
    lines = open(a.params).read().splitlines()
    p = json.loads(lines[0][2:])
    known = {}
    if a.check:
        hdr = lines[1].split("\t")
        for ln in lines[2:]:
            f = dict(zip(hdr, ln.split("\t")))
            known[f["label"]] = int(f["l1_fee_node_wei"])
    rows = []
    for path in a.tsv:
        for line in open(path):
            line = line.rstrip("\n")
            if not line:
                continue
            label, diff, gas, to, data = line.split("\t")
            d = bytes.fromhex(data[2:])
            sb = signed_tx(to, d, int(gas))
            f_s = flz_len(sb)
            node = fjord_fee(f_s, p)
            cd_len, cd_zero, cd_gas, floor = calldata_stats(d)
            if a.check and label in known:
                print(f"{label}: {node} vs {known[label]} ({(node / known[label] - 1) * 100:+.2f}%)", file=sys.stderr)
            rows.append([label, int(diff), int(gas), cd_len, cd_zero, cd_gas, floor, len(sb), f_s, node,
                         "", "", "", int(gas) * p["base_fee"], int(gas) * (p["base_fee"] + TIP)])
    hdr = ["label", "gasleft_diff", "tx_gas", "calldata_bytes", "calldata_zero", "calldata_gas",
           "eip7623_floor", "signed_tx_bytes", "flz_signed", "l1_fee_node_wei", "l1_fee_gpo_unsigned_wei",
           "l1_fee_gpo_signed_wei", "l1_fee_upper_bound_wei", "l2_fee_basefee_wei", "l2_fee_with_tip_wei"]
    with open(a.out, "w") as f:
        f.write("# " + json.dumps(p) + " (l1big.py: stand-in signature)\n")
        f.write("\t".join(hdr) + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")


if __name__ == "__main__":
    main()
