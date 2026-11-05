#!/usr/bin/env python3
"""Summary of the P5 rows: transaction gas, L2 fee at the fork block's base
fee and at the effective-price multiplier 2.0, the L1 data fee (Fjord,
l1big.py), USD at 2,401.44 USD/ETH, and the ratio to the registered sketch
values for the comparison rows.

Usage: summarize_p5.py P5_L1FEE.tsv > summary.tsv
"""
import sys

ETH_USD = 2401.44
BASE = 5_000_000  # wei per gas, 0.005 gwei

# comparison rows fixed before measuring: label -> (sketch gas, units in the row)
SKETCH = {
    "P5 self-submission, one unit, m=32 all signed, tx gas": (650_180, 1),
    "P5 self-submission, one unit, m=32 none signed, tx gas": (417_429, 1),
    "P5 bundled anchor, P=8 profiles, m=32 all signed, tx gas": (8 * 650_180, 8),
    "P5 shared SAMPLE request (set), tx gas": (51_550, 1),
    "P5 shared (set 2) value acceptance (ECVRF), tries 2, tx gas": (80_900, 1),
    "P5 shared SAMPLE request through Chainlink VRF v2.5 (set, native), tx gas": (96_000, 1),
    "P5 bundled release, N=8 accounts, m=8 sales, k=4 cases each, tx gas": (8 * 146_398, 8),
    "P5 proof call, tier 1a Pyth Pro one feed, depth 5, tx gas": (31_315, 1),
    "P5 proof call, tier 0 storage proof (fixture), depth 5, tx gas": (552_125, 1),
    "P5 non-delivery dispute (honest seller), open, depth 5, 1 KB, tx gas": (122_222, 1),
    "P5 key dispute (honest seller), open, depth 5, 1 KB, tx gas": (122_222, 1),
    "P5 non-delivery dispute (honest seller), seller posts ct and k, 4 KB, tx gas": (186_500, 1),
    "P5 key dispute (honest seller), seller reveals k, 1 KB, tx gas": (51_965, 1),
    "P5 non-delivery dispute (honest seller), decryption challenge, deposit to seller, 4 KB, tx gas": (186_500, 1),
    "P5 non-delivery dispute (honest seller), decryption challenge, deposit to seller, 1 KB, tx gas": (64_010, 1),
}
# upper-case sketch (lower + 5,200 + 900 per level, depth 5) for the proof calls
UPPER = {
    "P5 proof call, tier 1a Pyth Pro one feed, depth 5, tx gas": 31_315 + 5_200 + 4_500,
    "P5 proof call, tier 0 storage proof (fixture), depth 5, tx gas": 552_125 + 5_200 + 4_500,
}


def main():
    lines = open(sys.argv[1]).read().splitlines()
    hdr = lines[1].split("\t")
    out = ["label", "tx_gas", "calldata_bytes", "eip7623_floor", "l2_usd_base", "l2_usd_x2", "l1_usd",
           "total_usd_base", "l1_share_base", "total_usd_x2", "sketch_gas", "ratio", "ratio_upper", "flag"]
    print("\t".join(out))
    for ln in lines[2:]:
        f = dict(zip(hdr, ln.split("\t")))
        g = int(f["tx_gas"])
        l1 = int(f["l1_fee_node_wei"])
        l2 = g * BASE
        usd = lambda w: w / 1e18 * ETH_USD
        row = [f["label"].replace(", tx gas", ""), g, f["calldata_bytes"], f["eip7623_floor"],
               "%.6f" % usd(l2), "%.6f" % usd(2 * l2), "%.7f" % usd(l1), "%.6f" % usd(l2 + l1),
               "%.2f%%" % (100 * l1 / (l2 + l1)), "%.6f" % usd(2 * l2 + l1)]
        sk = SKETCH.get(f["label"])
        if sk:
            r = g / sk[0]
            up = UPPER.get(f["label"])
            ru = g / up if up else None
            flag = "replace (r > 2)" if r > 2 else ("below half (r < 1/2)" if r < 0.5 else "keep")
            row += [sk[0], "%.3f" % r, "%.3f" % ru if ru else "", flag]
        else:
            row += ["", "", "", ""]
        print("\t".join(str(x) for x in row))


if __name__ == "__main__":
    main()
