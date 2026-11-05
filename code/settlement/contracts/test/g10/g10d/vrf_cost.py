#!/usr/bin/env python3
"""Per-request cost of Chainlink VRF v2.5 on Base from the G10d-2 fork rows.

Inputs: vrf.tsv (run_vrf.py) and vrf_l1fee.tsv (l1big.py on the same
transactions). Fits fulfill gas = a + b * (hash-to-curve tries) on the
steady-state rows (rep >= 2) of each payment option, takes the expected try
count 2 (each candidate x has y^2 a square with probability about 1/2), and
prices the request transaction plus the subscription charge
  native: (gp * billed + L1cost) * (100 + 60) / 100
  LINK:   (gp * billed + L1cost) * (100 + 50) / 100, in ETH at the LINK/ETH feed
with billed = fulfill gas - (21,000 + calldata gas) + gasAfterPaymentCalculation,
as read back from the measured payments. Flat fees are 0 on Base.

Usage: vrf_cost.py vrf.tsv vrf_l1fee.tsv
"""
import csv
import sys

ETH_USD = 2401.44
WEI_PER_LINK = 5070633698959211  # LINK/ETH feed at block 52,977,000
G10C_GAS = 51_550 + 80_900
GAS_USD = 5_000_000 * ETH_USD / 1e18  # 1 gas at 0.005 gwei


def fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def main():
    rows = [r for r in csv.DictReader((ln for ln in open(sys.argv[1]) if not ln.startswith("#")), delimiter="\t")]
    l1 = {r["label"]: int(r["l1_fee_node_wei"]) for r in
          csv.DictReader((ln for ln in open(sys.argv[2]) if not ln.startswith("#")), delimiter="\t")}
    print("tries per run:", {m: [int(r["h2c_tries"]) for r in rows if r["mode"] == m] for m in ("native", "link")})
    allt = [int(r["h2c_tries"]) for r in rows]
    print(f"mean tries over {len(allt)} runs: {sum(allt) / len(allt):.2f} (expected 2)")
    out = {}
    for mode, prem in (("native", 60), ("link", 50)):
        st = [r for r in rows if r["mode"] == mode and int(r["rep"]) >= 2]
        t = [int(r["h2c_tries"]) for r in st]
        fg = [int(r["fulfill_gas"]) for r in st]
        bg = [int(r["billed_gas"]) for r in st]
        a, b = fit(t, fg)
        ab, bb = fit(t, bg)
        req = sorted({int(r["request_gas"]) for r in st})
        l1c = int(st[0]["l1_cost_wei"])
        e_f, e_b = a + 2 * b, ab + 2 * bb
        print(f"== {mode}: steady rows {len(st)}, request gas {req}, fulfill gas = {a:.0f} + {b:.0f} x tries,"
              f" billed = {ab:.0f} + {bb:.0f} x tries; L1 cost charged {l1c} wei")
        print(f"   expected (2 tries): fulfill tx gas {e_f:.0f}, billed gas {e_b:.0f}")
        first = [r for r in rows if r["mode"] == mode and r["rep"] == "1"][0]
        print(f"   first request of the consumer/mode: request {first['request_gas']}, fulfill {first['fulfill_gas']}"
              f" ({first['h2c_tries']} tries), billed {first['billed_gas']}")
        req_l1 = l1[f"vrf_{mode}_request_2"]
        ful_l1 = l1[f"vrf_{mode}_fulfill_2"]
        for mult in (1.0, 1.1018, 2.0):
            gp = 5_000_000 * mult
            pay = (gp * e_b + l1c) * (100 + prem) / 100
            req_fee = gp * req[-1] + req_l1
            node_cost = gp * e_f + ful_l1
            tot = pay + req_fee
            line = (f"   gp {gp / 1e9:.5f} gwei: request tx {req_fee * ETH_USD / 1e18:.6f} USD,"
                    f" charge {pay * ETH_USD / 1e18:.6f} USD")
            if mode == "link":
                line += f" (= {pay / WEI_PER_LINK:.3e} LINK)"
            line += (f", total {tot * ETH_USD / 1e18:.6f} USD = {tot * ETH_USD / 1e18 / GAS_USD:,.0f} gas-equiv at"
                     f" 0.005 gwei; node's own fulfill tx cost {node_cost * ETH_USD / 1e18:.6f} USD;"
                     f" G10c ECVRF at same gp {G10C_GAS * gp * ETH_USD / 1e18:.6f} USD; ratio"
                     f" {tot / (G10C_GAS * gp):.2f}")
            print(line)
        out[mode] = (e_f, e_b)
    print(f"G10c ECVRF path: {G10C_GAS} gas = {G10C_GAS * GAS_USD:.6f} USD at 0.005 gwei")


if __name__ == "__main__":
    main()
