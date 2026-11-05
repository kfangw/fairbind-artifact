#!/usr/bin/env python3
"""Samples the Base fee inputs over the days before the fork block, for the
sensitivity of the G10b costs: L2 base fee, the GasPriceOracle L1 inputs
(l1BaseFee, blobBaseFee, baseFeeScalar, blobBaseFeeScalar) and the Chainlink
ETH/USD feed on Base. Read-only eth_call and eth_getBlockByNumber, spaced out
to keep the request count low (6 requests per sample).

Usage: l1params.py --rpc URL --block N --days 90 --step 3 --out OUT.tsv
"""
import argparse
import json
import subprocess
import time

GPO = "0x420000000000000000000000000000000000000F"
ETH_USD = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"  # Chainlink ETH / USD on Base, 8 decimals
BLOCKS_PER_DAY = 43_200  # 2 s blocks


def cast(*args):
    r = subprocess.run(["cast", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--block", type=int, required=True)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for d in range(0, a.days + 1, a.step):
        b = str(a.block - d * BLOCKS_PER_DAY)
        rpc = ["--rpc-url", a.rpc, "--block", b]
        blk = json.loads(cast("block", b, "--json", "--rpc-url", a.rpc))
        vals = [b, str(int(blk["timestamp"], 16)), str(int(blk["baseFeePerGas"], 16))]
        for sig in ("l1BaseFee()(uint256)", "blobBaseFee()(uint256)", "baseFeeScalar()(uint32)", "blobBaseFeeScalar()(uint32)"):
            vals.append(cast("call", GPO, sig, *rpc).split()[0])
            time.sleep(0.3)
        rd = cast("call", ETH_USD, "latestRoundData()(uint80,int256,uint256,uint256,uint80)", *rpc).split("\n")
        vals.append(rd[1].split()[0])
        rows.append(vals)
        time.sleep(0.3)
    with open(a.out, "w") as f:
        f.write("block\ttimestamp\tl2_base_fee_wei\tl1_base_fee_wei\tblob_base_fee_wei\tbase_fee_scalar\tblob_base_fee_scalar\teth_usd_1e8\n")
        for r in rows:
            f.write("\t".join(r) + "\n")


if __name__ == "__main__":
    main()
