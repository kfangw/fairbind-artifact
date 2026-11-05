#!/usr/bin/env python3
"""Samples the Base L2 base fee over the days before the fork block (S5).

Every STEP days back from the fork block (43,200 blocks a day), one
eth_feeHistory request returns the base fee of the 1,024 blocks ending at that
block (about 34 minutes). One request per point, read-only, public RPC.
Writes one row per block (point, block, base fee in wei, gas used ratio).

Usage: basefee90.py --rpc URL --block N --days 90 --step 3 --out OUT.tsv
"""
import argparse
import json
import subprocess
import time

BLOCKS_PER_DAY = 43_200
WINDOW = 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--block", type=int, required=True)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.out, "w") as f:
        f.write("point_day\tblock\tbase_fee_wei\tgas_used_ratio\n")
        for d in range(0, a.days + 1, a.step):
            end = a.block - d * BLOCKS_PER_DAY
            r = subprocess.run(["cast", "rpc", "eth_feeHistory", str(WINDOW), hex(end), "[]", "--rpc-url", a.rpc],
                               capture_output=True, text=True, check=True)
            h = json.loads(r.stdout)
            first = int(h["oldestBlock"], 16)
            fees = [int(x, 16) for x in h["baseFeePerGas"]][:WINDOW]  # the last entry is the next block's
            for i, (bf, ratio) in enumerate(zip(fees, h["gasUsedRatio"])):
                f.write(f"{d}\t{first + i}\t{bf}\t{ratio}\n")
            time.sleep(1.0)


if __name__ == "__main__":
    main()
