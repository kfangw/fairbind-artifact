#!/usr/bin/env python3
"""Fits the release-call gas rows of ReleaseGas.t.sol (forge test --isolate
-vv log) to gas = fixed + per_sale * m by least squares, per series, and
compares them with the cost model's release constants (k11b.py: REL_F
114,624 with the hold ledger, REL_M 2,930 per sale, REL_K 2,083 per closed
case) and with the earlier contract's single cursor call.

usage: fit_release_gas.py <release-gas.log> [<old-release.log>]
"""
import re
import sys

TX_CAP = 2 ** 24
REL_F, REL_M, REL_K = 114_624, 2_930, 2_083


def fit(pts):
    n = len(pts)
    sx = sum(m for m, _ in pts)
    sy = sum(g for _, g in pts)
    sxx = sum(m * m for m, _ in pts)
    sxy = sum(m * g for m, g in pts)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    res = max(abs(g - (a + b * m)) for m, g in pts)
    return a, b, res


def rows(path, pat):
    out = {}
    for line in open(path, encoding="utf-8"):
        mm = re.search(pat, line)
        if mm:
            out.setdefault(mm.group(1), []).append((int(mm.group(2)), int(mm.group(3))))
    return out


def main():
    series = rows(sys.argv[1], r"row series=(\w+) m=(\d+) gas=(\d+)")
    print("Release-call gas by sales m per call (forge test --isolate, transaction gas incl. 21,000 intrinsic)")
    print("fit: gas = fixed + per_sale * m (least squares); max_m = largest m with gas < 2^24 by the fit\n")
    fits = {}
    for name in ("check", "check_proven", "check_fail", "payunit", "passpay", "inline", "inline_proven", "pass"):
        pts = sorted(set(series.get(name, [])))
        if not pts:
            continue
        print("%-14s points %s" % (name, ", ".join("%d:%d" % p for p in pts)))
        if len(set(m for m, _ in pts)) < 2:
            print("%-14s mean %.0f\n" % ("", sum(g for _, g in pts) / len(pts)))
            continue
        a, b, res = fit(pts)
        fits[name] = (a, b)
        mx = int((TX_CAP - 1 - a) // b) if b > 0 else None
        print("%-14s fixed %.0f, per sale %.1f, max residual %.0f, max_m under 2^24 %s\n" % ("", a, b, res, mx))
    if "check" in fits and "payunit" in fits:
        c, p = fits["check"], fits["payunit"]
        print("per-sale release gas, check unit + payment unit: %.1f + %.1f = %.1f" % (c[1], p[1], c[1] + p[1]))
    if "inline" in fits:
        a, b = fits["inline"]
        print("one cursor call doing check, pass and payment: fixed %.0f, per sale %.1f" % (a, b))
    if "check" in fits and "check_proven" in fits:
        print("per closed case (proven sampled sale) in a check unit, against an unsampled sale: %+.1f" % (fits["check_proven"][1] - fits["check"][1]))
    if "check" in fits and "check_fail" in fits:
        print("per failing sampled sale in a check unit, against an unsampled sale: %+.1f" % (fits["check_fail"][1] - fits["check"][1]))
    print("\ncost model (k11b.py): REL_F %d fixed per release transaction, REL_M %d per sale, REL_K %d per closed case;"
          " model capacity floor((2^24 - REL_F) / REL_M) = %d sales (q = 0)" % (REL_F, REL_M, REL_K, (TX_CAP - REL_F) // REL_M))
    if "inline" in fits:
        a, b = fits["inline"]
        print("measured against the model: fixed %.2fx REL_F, per sale %.2fx REL_M" % (a / REL_F, b / REL_M))
    if len(sys.argv) > 2:
        old = rows(sys.argv[2], r"old (release) n=(\d+) gas=(\d+)").get("release", [])
        if old:
            pts = sorted(old)
            a, b, res = fit(pts)
            print("\nearlier contract (vrf 7a96ae5), one cursor call: points %s" % ", ".join("%d:%d" % q for q in pts))
            print("fixed %.0f, per sale %.1f (max residual %.0f); above 2^24 from %d sales" % (a, b, res, int((TX_CAP - a) // b) + 1))


if __name__ == "__main__":
    main()
