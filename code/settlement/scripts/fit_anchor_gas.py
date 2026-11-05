#!/usr/bin/env python3
"""Fits the anchor, completion and pull gas rows of AnchorLoad.t.sol
(forge test --isolate -vv log) to gas = fixed + per_record * m by least
squares, per series, summarizes the load rows (largest transaction per call
kind), and sets the fits beside the cost model's anchor terms (k11b.py
lines 160-166 and 191: G10B_F 129,299 / 148,812 fixed and G10B_M 9,004 /
15,668 per sale, unsigned / signed leaves; CAP_GAS 1,564 / 924 sales per
anchor transaction).

usage: fit_anchor_gas.py <anchor-load.log>
"""
import re
import sys

TX_CAP = 2 ** 24
G10B_F = {"unsigned": 129_299, "signed": 148_812}
G10B_M = {"unsigned": 9_004, "signed": 15_668}
CAP_GAS = {"unsigned": 1_564, "signed": 924}


def fit(pts):
    n = len(pts)
    sx = sum(m for m, _ in pts)
    sy = sum(g for _, g in pts)
    sxx = sum(m * m for m, _ in pts)
    sxy = sum(m * g for m, g in pts)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    return a, b, max(abs(g - (a + b * m)) for m, g in pts)


def main():
    text = open(sys.argv[1], encoding="utf-8").read().splitlines()
    series, load = {}, {}
    for line in text:
        mm = re.search(r"row series=(\w+) m=(\d+) gas=(\d+)", line)
        if mm:
            series.setdefault(mm.group(1), []).append((int(mm.group(2)), int(mm.group(3))))
        mm = re.search(r"load kind=(\w+) n=(\d+) (\w+) (\d+) gas=(\d+)", line)
        if mm:
            k = (mm.group(1), int(mm.group(2)), mm.group(3))
            load.setdefault(k, []).append(int(mm.group(5)))
    print("Anchor, completion and pull gas by records m per call (forge test --isolate, transaction gas incl. 21,000)")
    print("unit_<kind>: a non-final anchor unit of m leaves; complete_<kind>: the completing unit (one leaf) whose")
    print("transaction moves the transfers of m = min(count, 256) records; chunk_<kind>: pullCompletion over m records;")
    print("pullsale_<kind>: pullSale of one sale. Kinds: plain (unsigned, answered), marked (u_n = 1), accepted (sigma_B, a = 1).\n")
    fits = {}
    for name in sorted(series):
        pts = sorted(series[name])
        print("%-18s points %s" % (name, ", ".join("%d:%d" % p for p in pts)))
        if len(set(m for m, _ in pts)) < 2:
            print("%-18s mean %.0f\n" % ("", sum(g for _, g in pts) / len(pts)))
            continue
        a, b, res = fit(pts)
        fits[name] = (a, b)
        mx = int((TX_CAP - 1 - a) // b) if b > 0 else None
        print("%-18s fixed %.0f, per record %.1f, max residual %.0f, max m under 2^24 %s\n" % ("", a, b, res, mx))
    for kind in ("marked", "accepted"):
        if "chunk_" + kind in fits and "chunk_plain" in fits:
            print("per %s record in a pull chunk, beyond a plain record: %+.1f" % (kind, fits["chunk_" + kind][1] - fits["chunk_plain"][1]))
    print("\ncost model (k11b.py): anchor transaction gas = G10B_F + G10B_M x; unsigned %d + %d x, signed %d + %d x;"
          " CAP_GAS %d unsigned / %d signed sales per anchor transaction" % (
              G10B_F["unsigned"], G10B_M["unsigned"], G10B_F["signed"], G10B_M["signed"], CAP_GAS["unsigned"], CAP_GAS["signed"]))
    for kind, mk in (("plain", "unsigned"), ("marked", "unsigned"), ("accepted", "signed")):
        if "unit_" + kind in fits:
            a, b = fits["unit_" + kind]
            print("unit_%s against the %s model: fixed %.2fx, per leaf %.2fx" % (kind, mk, a / G10B_F[mk], b / G10B_M[mk]))
    if load:
        print("\nload (one profile epoch of n sales of v_min): transactions per call kind, largest gas")
        for (kind, n, call) in sorted(load):
            g = load[(kind, n, call)]
            print("  %-7s n=%-5d %-15s %3d transactions, largest %d" % (kind, n, call, len(g), max(g)))
        print("  every row is below 2^24 = %d (the tests assert it)" % TX_CAP)


if __name__ == "__main__":
    main()
