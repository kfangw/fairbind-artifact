#!/usr/bin/env python3
"""Reads the receipt and the block base fee of each sampled settlement (G10d-1).

For each tx_hash of the sample table: eth_getTransactionReceipt, then
eth_getBlockByNumber(receipt.blockNumber, false) for baseFeePerGas (one block
request per distinct block). Public RPC, read-only, one request at a time
with a pause. Keeps the raw responses (logs and bloom dropped) in a JSONL
file and writes one row per transaction.

Usage: fetch_receipts.py --rpc URL --sample sample.tsv --raw raw.jsonl --out OUT.tsv
"""
import argparse
import csv
import json
import time

import requests

FIELDS = ["gasUsed", "effectiveGasPrice", "l1Fee", "l1GasUsed", "l1GasPrice", "l1BaseFeeScalar",
          "l1BlobBaseFee", "l1BlobBaseFeeScalar", "operatorFeeScalar", "operatorFeeConstant",
          "daFootprintGasScalar", "blobGasUsed", "type", "status"]


def rpc(url, method, params, n=[0]):
    for k in range(5):
        try:
            n[0] += 1
            r = requests.post(url, json={"jsonrpc": "2.0", "id": n[0], "method": method, "params": params},
                              timeout=30)
            j = r.json()
            if "result" in j and j["result"] is not None:
                return j["result"]
            print("retry", method, params[0], j.get("error"))
        except Exception as e:  # noqa: BLE001
            print("retry", method, params[0], e)
        time.sleep(2.0 * (k + 1))
    raise SystemExit(f"failed {method} {params}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pause", type=float, default=0.25)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.sample), delimiter="\t"))
    blocks = {}
    nreq = 0
    with open(a.raw, "w") as raw, open(a.out, "w") as out:
        out.write("\t".join(["window", "date", "facilitator", "tx_hash", "block", "base_fee"] + FIELDS) + "\n")
        for i, s in enumerate(rows):
            r = rpc(a.rpc, "eth_getTransactionReceipt", [s["tx_hash"]]); nreq += 1
            r.pop("logs", None); r.pop("logsBloom", None)
            bn = r["blockNumber"]
            if bn not in blocks:
                time.sleep(a.pause)
                b = rpc(a.rpc, "eth_getBlockByNumber", [bn, False]); nreq += 1
                blocks[bn] = int(b["baseFeePerGas"], 16)
            raw.write(json.dumps({"receipt": r, "baseFeePerGas": blocks[bn]}) + "\n")
            vals = []
            for f in FIELDS:
                v = r.get(f)
                vals.append("" if v is None else (str(int(v, 16)) if isinstance(v, str) and v.startswith("0x") else str(v)))
            out.write("\t".join([s["window"], s["date"], s["facilitator"], s["tx_hash"], str(int(bn, 16)),
                                 str(blocks[bn])] + vals) + "\n")
            if i % 50 == 0:
                print(i, nreq, flush=True)
            time.sleep(a.pause)
    print("done rows", len(rows), "requests", nreq)


if __name__ == "__main__":
    main()
