#!/usr/bin/env python3
"""L1 data fee of the G10b measured transactions on the Base fork.

For every row of the receipts tables written by the G10b tests (label, gasleft
difference, transaction gas used, target, calldata), this script builds the
EIP-1559 transaction a sender would sign on Base (chain 8453) with a throwaway
key, then computes the L1 data fee three ways at the fork block:

  gpo_unsigned  GasPriceOracle.getL1Fee(unsigned tx). Since Fjord the oracle
                compresses its input with FastLZ and adds 68 bytes for the
                signature, so this is the oracle's documented estimate.
  gpo_signed    GasPriceOracle.getL1Fee(signed tx bytes). Counts the
                signature twice (68 bytes added on top of a signed input).
  node          The fee the node charges: the Fjord formula on the FastLZ size
                of the full signed transaction (op-geth / reth
                L1CostFunc, no 68-byte addition). FastLZ is reimplemented
                below and checked against the oracle on every row
                (formula(flz(unsigned) + 68) must equal gpo_unsigned).

Also GasPriceOracle.getL1FeeUpperBound(len(unsigned)) and the EIP-7623 floor.

The key is read from a file and never printed. Only a local fork RPC is used.
Usage: l1fee.py --key-file K --rpc URL --block N --out OUT.tsv IN.tsv...
"""
import argparse
import json
import subprocess
import sys

GPO = "0x420000000000000000000000000000000000000F"
CHAIN_ID = 8453
NONCE = 7
MAX_FEE = 10_000_000  # 0.01 gwei cap; the transaction pays base fee + tip
TIP = 1_000_000  # 0.001 gwei, the median tip in the 20 blocks to the fork block


def cast(*args):
    r = subprocess.run(["cast", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cast {args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def flz_len(ib: bytes) -> int:
    """FastLZ (level 1) compressed length, as op-geth FlzCompressLen and
    Solady LibZip.flzCompress compute it."""
    M = 0xFFFFFFFF
    n = 0
    ht = [0] * 8192

    def u24(i):
        return ib[i] | (ib[i + 1] << 8) | (ib[i + 2] << 16)

    def cmp(p, q, e):
        l = 0
        e = (e - q) & M
        while l < e:
            if ib[p + l] != ib[q + l]:
                e = 0
            l += 1
        return l

    def literals(r):
        nonlocal n
        n += 0x21 * (r // 0x20)
        r %= 0x20
        if r != 0:
            n += r + 1

    def match(l):
        nonlocal n
        l -= 1
        n += 3 * (l // 262)
        n += 3 if l % 262 >= 6 else 2

    def hsh(v):
        return (((2654435769 * v) & M) >> 19) & 0x1FFF

    def set_next(ip):
        ht[hsh(u24(ip))] = ip
        return ip + 1

    a = 0
    ip_limit = len(ib) - 13 if len(ib) >= 13 else 0
    ip = a + 2
    while ip < ip_limit:
        r = 0
        while True:
            s = u24(ip)
            h = hsh(s)
            r = ht[h]
            ht[h] = ip
            d = (ip - r) & M
            if ip >= ip_limit:
                break
            ip += 1
            if d <= 0x1FFF and s == u24(r):
                break
        if ip >= ip_limit:
            break
        ip -= 1
        if ip > a:
            literals(ip - a)
        l = cmp(r + 3, ip + 3, ip_limit + 9)
        match(l)
        ip = set_next(set_next(ip + l))
        a = ip
    literals(len(ib) - a)
    return n


def fjord_fee(flz, p):
    est = max(p["min_size"] * 1_000_000, p["intercept"] + p["coef"] * flz)
    scaled = p["base_scalar"] * 16 * p["l1_base_fee"] + p["blob_scalar"] * p["blob_base_fee"]
    return est * scaled // 1_000_000_000_000


def calldata_stats(data: bytes):
    z = data.count(0)
    nz = len(data) - z
    return len(data), z, 4 * z + 16 * nz, 21000 + 10 * (z + 4 * nz)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--block", required=True, type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("tsv", nargs="+")
    a = ap.parse_args()
    key = open(a.key_file).read().strip()
    blk = str(a.block)
    rpc = ["--rpc-url", a.rpc, "--block", blk]

    def call(sig, *args):
        return cast("call", GPO, sig, *args, *rpc).split()[0]

    p = {
        "l1_base_fee": int(call("l1BaseFee()(uint256)")),
        "blob_base_fee": int(call("blobBaseFee()(uint256)")),
        "base_scalar": int(call("baseFeeScalar()(uint32)")),
        "blob_scalar": int(call("blobBaseFeeScalar()(uint32)")),
        # Fjord constants of GasPriceOracle (checked against getL1Fee below)
        "min_size": 100,
        "intercept": -42_585_600,
        "coef": 836_500,
    }
    p["gpo_version"] = cast("call", GPO, "version()(string)", *rpc).strip('"')
    block = json.loads(cast("block", blk, "--json", "--rpc-url", a.rpc))
    p["base_fee"] = int(block["baseFeePerGas"], 16)
    p["block"] = a.block
    p["timestamp"] = int(block["timestamp"], 16)
    print(json.dumps(p), file=sys.stderr)

    sender = cast("wallet", "address", "--private-key", key)
    rows = []
    for path in a.tsv:
        for line in open(path):
            line = line.rstrip("\n")
            if not line:
                continue
            label, diff, gas, to, data = line.split("\t")
            gas = int(gas)
            common = ["--chain", str(CHAIN_ID), "--nonce", str(NONCE), "--gas-limit", str(gas),
                      "--gas-price", str(MAX_FEE), "--priority-gas-price", str(TIP), to, data]
            signed = cast("mktx", "--private-key", key, *common)
            unsigned = cast("mktx", "--raw-unsigned", "--from", sender, *common)
            sb = bytes.fromhex(signed[2:])
            ub = bytes.fromhex(unsigned[2:])
            g_uns = int(call("getL1Fee(bytes)(uint256)", unsigned))
            g_sig = int(call("getL1Fee(bytes)(uint256)", signed))
            g_ub = int(call("getL1FeeUpperBound(uint256)(uint256)", str(len(ub))))
            f_s, f_u = flz_len(sb), flz_len(ub)
            check = fjord_fee(f_u + 68, p)
            if check != g_uns:
                raise SystemExit(f"FastLZ check failed on {label}: {check} != {g_uns}")
            node = fjord_fee(f_s, p)
            cd_len, cd_zero, cd_gas, floor = calldata_stats(bytes.fromhex(data[2:]))
            rows.append([label, int(diff), gas, cd_len, cd_zero, cd_gas, floor, len(sb), f_s,
                         node, g_uns, g_sig, g_ub, gas * p["base_fee"], gas * (p["base_fee"] + TIP)])
    hdr = ["label", "gasleft_diff", "tx_gas", "calldata_bytes", "calldata_zero", "calldata_gas",
           "eip7623_floor", "signed_tx_bytes", "flz_signed", "l1_fee_node_wei", "l1_fee_gpo_unsigned_wei",
           "l1_fee_gpo_signed_wei", "l1_fee_upper_bound_wei", "l2_fee_basefee_wei", "l2_fee_with_tip_wei"]
    with open(a.out, "w") as f:
        f.write("# " + json.dumps(p) + "\n")
        f.write("\t".join(hdr) + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    print(f"{len(rows)} rows, FastLZ check passed on every row", file=sys.stderr)


if __name__ == "__main__":
    main()
