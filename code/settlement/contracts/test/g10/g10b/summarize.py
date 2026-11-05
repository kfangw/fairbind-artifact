#!/usr/bin/env python3
"""Joins the G10b tables into one: the earlier G10 value (gasleft difference
under Cancun, from the G10 logs), the transaction gas used under Cancun and
under Osaka on the fork, the EIP-7623 floor, and the fees in USD.

Usage: summarize.py --l1 l1fee.tsv --cancun 'g10b-out/m*_cancun.tsv'
                    --old 'old/g10_m*.log' --params l1params.tsv --eth 2401.44 --out OUT.tsv
"""
import argparse
import glob
import json
import re
import statistics

TIP = 1_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--l1", required=True)
    ap.add_argument("--cancun", required=True)
    ap.add_argument("--old", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--eth", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    old = {}
    for f in glob.glob(a.old):
        for line in open(f):
            m = re.match(r"^\s+(.*tx gas) (\d+)$", line.rstrip())
            if m and "(transaction gas used" not in line:
                old[m.group(1)] = int(m.group(2))
    can = {}
    for f in glob.glob(a.cancun):
        for line in open(f):
            if line.strip():
                lab, diff, gas = line.split("\t")[:3]
                can[lab] = int(gas)

    lines = open(a.l1).read().splitlines()
    p = json.loads(lines[0][2:])
    hdr = lines[1].split("\t")
    rows = [dict(zip(hdr, l.split("\t"))) for l in lines[2:]]

    # sensitivity of the L1 fee to the L1 inputs over the sampled days
    pl = open(a.params).read().splitlines()
    ph = pl[0].split("\t")
    samples = [dict(zip(ph, l.split("\t"))) for l in pl[1:]]

    def scaled(d):
        return 16 * int(d["base_fee_scalar"]) * int(d["l1_base_fee_wei"]) + int(d["blob_base_fee_scalar"]) * int(d["blob_base_fee_wei"])

    ref = 16 * p["base_scalar"] * p["l1_base_fee"] + p["blob_scalar"] * p["blob_base_fee"]
    ratios = sorted(scaled(d) / ref for d in samples)
    q = lambda xs, f: xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))]
    sens = {"median": statistics.median(ratios), "p90": q(ratios, 0.9), "max": ratios[-1], "min": ratios[0], "n": len(ratios)}
    eths = [int(d["eth_usd_1e8"]) / 1e8 for d in samples]
    l2fees = [int(d["l2_base_fee_wei"]) for d in samples]

    usd = a.eth / 1e18
    out = []
    for r in rows:
        lab = r["label"]
        gas = int(r["tx_gas"])
        l2 = int(r["l2_fee_basefee_wei"])
        l2t = int(r["l2_fee_with_tip_wei"])
        l1 = int(r["l1_fee_node_wei"])
        out.append({
            "label": lab,
            "g10_old": old.get(lab, ""),
            "cancun_tx": can.get(lab, ""),
            "osaka_tx": gas,
            "floor": int(r["eip7623_floor"]),
            "floor_binds": "yes" if gas == int(r["eip7623_floor"]) else "",
            "calldata_bytes": int(r["calldata_bytes"]),
            "signed_bytes": int(r["signed_tx_bytes"]),
            "flz": int(r["flz_signed"]),
            "l2_usd": l2 * usd,
            "l2_tip_usd": l2t * usd,
            "l1_usd": l1 * usd,
            "l1_gpo_usd": int(r["l1_fee_gpo_unsigned_wei"]) * usd,
            "total_usd": (l2 + l1) * usd,
            "total_tip_usd": (l2t + l1) * usd,
            "l1_share": l1 / (l2 + l1),
            "l1_share_tip": l1 / (l2t + l1),
            "l1_share_p90": l1 * sens["p90"] / (l2 + l1 * sens["p90"]),
            "l1_share_max": l1 * sens["max"] / (l2 + l1 * sens["max"]),
        })
    keys = list(out[0].keys())
    with open(a.out, "w") as f:
        meta = dict(p, eth_usd=a.eth, l1_input_ratio_over_samples=sens,
                    eth_usd_samples={"min": min(eths), "median": statistics.median(eths), "max": max(eths)},
                    l2_base_fee_samples={"min": min(l2fees), "median": statistics.median(l2fees), "max": max(l2fees)})
        f.write("# " + json.dumps(meta) + "\n")
        f.write("\t".join(keys) + "\n")
        for o in out:
            f.write("\t".join(f"{o[k]:.3g}" if isinstance(o[k], float) else str(o[k]) for k in keys) + "\n")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
