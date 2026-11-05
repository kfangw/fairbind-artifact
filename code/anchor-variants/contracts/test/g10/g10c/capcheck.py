#!/usr/bin/env python3
"""Is the EIP-7825 per-transaction gas cap (2^24) in force on Base? (G10c-3)

1. Finds the first block where CLZ (EIP-7939, Osaka) executes, by bisection
   with eth_call of the G10b CLZ initcode (about 25 requests).
2. Reads 40 blocks spread over the 30 days before and 40 over the 30 days
   after that block and counts transactions with a gas limit above 2^24.
3. eth_simulateV1 with validation at the fork block, gas 2^24 + 1 (records
   whether the node's simulation rejects it).
Read-only, public RPC, spaced requests.

Usage: capcheck.py --rpc URL --block N
"""
import argparse
import json
import subprocess
import time

CAP = 1 << 24
DAY = 43_200


def rpc(url, method, *params):
    r = subprocess.run(["cast", "rpc", method, *params, "--rpc-url", url], capture_output=True, text=True)
    time.sleep(0.25)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[:200]}
    return {"result": json.loads(r.stdout)}


def clz(url, b):
    r = rpc(url, "eth_call", '{"data":"0x60011e60005260206000f3"}', hex(b))
    return "result" in r and str(r["result"]).endswith("ff")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--block", type=int, required=True)
    a = ap.parse_args()
    lo, hi = a.block - 180 * DAY, a.block
    print(f"CLZ at {lo}: {clz(a.rpc, lo)}, at {hi}: {clz(a.rpc, hi)}")
    while hi - lo > 1:
        m = (lo + hi) // 2
        if clz(a.rpc, m):
            hi = m
        else:
            lo = m
    ts = int(rpc(a.rpc, "eth_getBlockByNumber", hex(hi), "false")["result"]["timestamp"], 16)
    print(f"first block with CLZ: {hi} (timestamp {ts})")
    for name, start in (("30 days before", hi - 30 * DAY), ("30 days after", hi)):
        n = big = mx = 0
        for i in range(40):
            b = start + i * (30 * DAY // 40)
            blk = rpc(a.rpc, "eth_getBlockByNumber", hex(b), "true")["result"]
            for t in blk["transactions"]:
                g = int(t["gas"], 16)
                n += 1
                mx = max(mx, g)
                big += g > CAP
        print(f"{name}: 40 blocks, {n} transactions, max gas limit {mx}, above 2^24: {big}")
    call = {"from": "0x000000000000000000000000000000000000dEaD", "to": "0x000000000000000000000000000000000000bEEF",
            "gas": hex(CAP + 1), "maxFeePerGas": "0x3b9aca00", "maxPriorityFeePerGas": "0x0", "nonce": "0x0"}
    sim = {"blockStateCalls": [{"stateOverrides": {call["from"]: {"balance": "0xde0b6b3a7640000"}}, "calls": [call]}],
           "validation": True}
    r = rpc(a.rpc, "eth_simulateV1", json.dumps(sim), hex(a.block))
    out = r.get("error") or [(c.get("status"), c.get("gasUsed"), c.get("error")) for c in r["result"][0]["calls"]]
    print(f"eth_simulateV1 (validation) at {a.block}, gas 2^24 + 1: {out}")


if __name__ == "__main__":
    main()
