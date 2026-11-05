#!/usr/bin/env python3
"""Summary of the G10c rows on one price basis (G10b: the fork block's L2
base fee, Chainlink ETH/USD at the fork block, Fjord L1 fee on the signed
bytes), with the conversion to the K10 basis (0.006 gwei, 1,890 USD/ETH, the
Fjord L1 fee converted at 1,890), and the S5 sensitivity (90-day L2 base fee
from basefee90.py, ETH and L1 inputs from the G10b l1params sample).

Usage: summarize_g10c.py --l1 L1FEE.tsv... --basefee BASEFEE.tsv --params L1PARAMS.tsv --out OUT.tsv
"""
import argparse

X402 = 85_740  # G10b plain x402 transferWithAuthorization, payTo paid before
ETH = 2401.44
OLD_GWEI, OLD_ETH = 0.006, 1890.0


def pct(a, q):
    a = sorted(a)
    k = (len(a) - 1) * q
    i = int(k)
    return a[i] if i + 1 >= len(a) else a[i] + (a[i + 1] - a[i]) * (k - i)


def read(path):
    lines = [l for l in open(path).read().splitlines() if not l.startswith("#")]
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, l.split("\t"))) for l in lines[1:]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--l1", nargs="+", required=True)
    ap.add_argument("--basefee", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    bf = [int(r["base_fee_wei"]) for r in read(a.basefee)]
    par = read(a.params)
    unit = lambda r: 16 * int(r["base_fee_scalar"]) * int(r["l1_base_fee_wei"]) + int(r["blob_base_fee_scalar"]) * int(r["blob_base_fee_wei"])
    u0 = unit(par[0])
    ratios = [unit(r) / u0 for r in par]
    eths = [int(r["eth_usd_1e8"]) / 1e8 for r in par]
    s = {
        "bf_p50": pct(bf, 0.5), "bf_p95": pct(bf, 0.95), "bf_p99": pct(bf, 0.99), "bf_max": max(bf),
        "eth_p50": pct(eths, 0.5), "eth_p95": pct(eths, 0.95),
        "l1_p50": pct(ratios, 0.5), "l1_p95": pct(ratios, 0.95), "l1_max": max(ratios),
    }
    out = open(a.out, "w")
    out.write("# sensitivity inputs " + " ".join(f"{k}={v:.6g}" for k, v in s.items()) + "\n")
    hdr = ["label", "tx_gas", "over_x402", "calldata_bytes", "floor_binds", "l2_usd", "l1_usd", "total_usd", "l1_share",
           "old_l2_usd", "old_l1_usd", "old_total_usd", "total_usd_bf_p99", "total_usd_bf_max", "total_usd_p95_all"]
    out.write("\t".join(hdr) + "\n")
    for path in a.l1:
        for r in read(path):
            g = int(r["tx_gas"])
            l1w = int(r["l1_fee_node_wei"])
            l2 = g * 5e6 / 1e18 * ETH
            l1 = l1w / 1e18 * ETH
            old_l2 = g * OLD_GWEI * 1e9 / 1e18 * OLD_ETH
            old_l1 = l1w / 1e18 * OLD_ETH
            p99 = (g * s["bf_p99"] + l1w) / 1e18 * ETH
            pmax = (g * s["bf_max"] + l1w) / 1e18 * ETH
            p95all = (g * s["bf_p95"] + l1w * s["l1_p95"]) / 1e18 * s["eth_p95"]
            row = [r["label"], g, g - X402 if "settle" in r["label"] else "", r["calldata_bytes"],
                   "yes" if int(r["eip7623_floor"]) >= g else "", f"{l2:.6g}", f"{l1:.3g}", f"{l2 + l1:.6g}",
                   f"{l1 / (l1 + l2) * 100:.2f}%", f"{old_l2:.6g}", f"{old_l1:.3g}", f"{old_l2 + old_l1:.6g}",
                   f"{p99:.6g}", f"{pmax:.6g}", f"{p95all:.6g}"]
            out.write("\t".join(str(x) for x in row) + "\n")


if __name__ == "__main__":
    main()
