#!/usr/bin/env python3
"""Effective gas price of the sampled x402 settlements (G10d-1, M2).

Reads the receipts table of fetch_receipts.py and reports, for the whole
sample and per window, p50/p90/p99/mean of effectiveGasPrice, priority fee
(effectiveGasPrice - block baseFeePerGas), l1Fee, gasUsed, the L2 fee, the
total fee per settlement in USD at ETH = 2,401.44, and the multiplier of the
paid L2 fee over the base-fee-only basis (gasUsed x 0.005 gwei). Quantiles
are linear interpolation between order statistics (numpy's default, type 7).

Usage: analyze_m2.py receipts.tsv > summary.txt
"""
import csv
import sys
from collections import Counter, defaultdict

ETH_USD = 2401.44
BASIS = 5_000_000  # 0.005 gwei, the G10b/G10c L2 price basis


def q(xs, p):
    s = sorted(xs)
    h = (len(s) - 1) * p
    lo = int(h)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (h - lo)


def stats(xs):
    return q(xs, .5), q(xs, .9), q(xs, .99), sum(xs) / len(xs), min(xs), max(xs)


def show(name, xs, scale=1.0, fmt="{:.6g}"):
    v = stats([x * scale for x in xs])
    print(f"  {name:34s} " + "  ".join(fmt.format(x) for x in v))


def report(title, rows):
    print(f"== {title} (n = {len(rows)})")
    print("  " + " " * 34 + " p50  p90  p99  mean  min  max")
    egp = [int(r["effectiveGasPrice"]) for r in rows]
    bf = [int(r["base_fee"]) for r in rows]
    tip = [e - b for e, b in zip(egp, bf)]
    gas = [int(r["gasUsed"]) for r in rows]
    l1 = [int(r["l1Fee"]) for r in rows]
    l2 = [g * e for g, e in zip(gas, egp)]
    tot = [a + b for a, b in zip(l2, l1)]
    show("effectiveGasPrice (gwei)", egp, 1e-9)
    show("block base fee (gwei)", bf, 1e-9)
    show("priority fee (gwei)", tip, 1e-9)
    show("priority share of egp", [t / e for t, e in zip(tip, egp)])
    show("gasUsed", gas)
    show("L2 fee (USD)", l2, ETH_USD / 1e18)
    show("l1Fee (USD)", l1, ETH_USD / 1e18)
    show("total fee per settlement (USD)", tot, ETH_USD / 1e18)
    show("L1 share of total", [b / t for b, t in zip(l1, tot)])
    show("egp / 0.005 gwei", egp, 1 / BASIS)
    show("total / (gasUsed*0.005 gwei)", [t / (g * BASIS) for t, g in zip(tot, gas)])
    print(f"  ratio of sums: L2 paid / (gasUsed*0.005 gwei) = {sum(l2) / (sum(gas) * BASIS):.4f};"
          f" total paid / (gasUsed*0.005 gwei) = {sum(tot) / (sum(gas) * BASIS):.4f}")
    print(f"  base-fee-only fee at sample mean gasUsed: {sum(gas) / len(gas) * BASIS * ETH_USD / 1e18:.3e} USD")
    print(f"  base fee at the 0.005 gwei floor: {sum(b == BASIS for b in bf)} of {len(bf)}")
    c = Counter(tip)
    print("  most common priority fees (wei: count):",
          ", ".join(f"{k}: {v}" for k, v in c.most_common(8)))
    print(f"  priority = 0: {c[0]}; priority >= base fee: {sum(t >= b for t, b in zip(tip, bf))}")


def main():
    rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
    assert all(r["status"] == "1" for r in rows)
    for f in ("operatorFeeScalar", "operatorFeeConstant"):
        print(f"receipts with {f}: {sum(1 for r in rows if r[f] != '')} of {len(rows)}")
    print(f"distinct tx {len({r['tx_hash'] for r in rows})}, distinct blocks {len({r['block'] for r in rows})},"
          f" days {len({r['date'] for r in rows})}, facilitators {len({r['facilitator'] for r in rows})}")
    report("all", rows)
    by = defaultdict(list)
    for r in rows:
        by[r["window"]].append(r)
    for w in sorted(by):
        report(w, by[w])
    # per facilitator: median priority fee and share at >= base fee
    print("== per facilitator (n, median priority gwei, share priority >= base fee)")
    byf = defaultdict(list)
    for r in rows:
        byf[r["facilitator"]].append(int(r["effectiveGasPrice"]) - int(r["base_fee"]))
    for f in sorted(byf):
        t = byf[f]
        print(f"  {f} {len(t):3d} {q(t, .5) / 1e9:.6f} {sum(x >= BASIS for x in t) / len(t):.2f}")
    print("== per date (n, median egp gwei, share priority >= base fee)")
    byd = defaultdict(list)
    for r in rows:
        byd[r["date"]].append(r)
    for d in sorted(byd):
        t = byd[d]
        e = [int(r["effectiveGasPrice"]) for r in t]
        print(f"  {d} {len(t):3d} {q(e, .5) / 1e9:.6f} "
              f"{sum(int(r['effectiveGasPrice']) - int(r['base_fee']) >= BASIS for r in t) / len(t):.2f}")


if __name__ == "__main__":
    main()
