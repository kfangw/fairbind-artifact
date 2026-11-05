#!/usr/bin/env python3
"""Sets the release and anchor gas fits on the real USDC (Base fork) beside
the mock-token fits: the same rows ("row series=<s> m=<m> gas=<g>" of
ReleaseGas.t.sol and AnchorLoad.t.sol, forge test --isolate -vv) and the same
least-squares fit gas = fixed + per_record * m as fit_release_gas.py and
fit_anchor_gas.py. Optional third pair: the mock token on the same fork (the
control that separates the token from the fork). Ends with the measured
constants the P9 cost calculation takes from these fits.

usage: compare_usdc_gas.py <mock-release.log> <mock-anchor.log> <usdc-release.log> <usdc-anchor.log>
                           [<mockfork-release.log> <mockfork-anchor.log>]
"""
import re
import sys

TX_CAP = 2 ** 24
ORDER = ["check", "check_proven", "check_fail", "payunit", "passpay", "inline", "inline_proven", "pass",
         "unit_plain", "unit_marked", "unit_accepted", "complete_plain", "complete_marked", "complete_accepted",
         "chunk_plain", "chunk_marked", "chunk_accepted", "pullsale_marked", "pullsale_accepted"]


def rows(paths):
    s = {}
    for p in paths:
        for line in open(p, encoding="utf-8"):
            mm = re.search(r"row series=(\w+) m=(\d+) gas=(\d+)", line)
            if mm:
                s.setdefault(mm.group(1), []).append((int(mm.group(2)), int(mm.group(3))))
    return s


def fit(pts):
    if len(set(m for m, _ in pts)) < 2:
        return sum(g for _, g in pts) / len(pts), None
    n = len(pts)
    sx = sum(m for m, _ in pts)
    sy = sum(g for _, g in pts)
    sxx = sum(m * m for m, _ in pts)
    sxy = sum(m * g for m, g in pts)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return (sy - b * sx) / n, b


def pct(a, b):
    if a is None or b is None:
        return "  n/a"
    if a == 0:
        return "  0.0%" if b == 0 else "  inf"
    return "%+6.2f%%" % (100.0 * (b - a) / a)


def cap(a, b):
    return int((TX_CAP - 1 - a) // b) if b and b > 0 else None


def main():
    a = sys.argv[1:]
    mock = rows(a[0:2])
    usdc = rows(a[2:4])
    ctrl = rows(a[4:6]) if len(a) >= 6 else None
    print("Release and anchor gas: real USDC (FiatTokenV2_2 at 0x8335...2913, Base state at block 52977000) against the")
    print("mock token (logs/anchor-units, 7c571a8). forge test --isolate, transaction gas incl. 21,000; fit gas = fixed + per * m.")
    print("diff = (USDC - mock) / mock. pullsale_* rows are single sales (mean of two).\n")
    hdr = "%-18s %10s %9s | %10s %9s | %8s %8s | %6s %6s" % ("series", "mock fix", "mock per", "USDC fix", "USDC per", "d fix", "d per", "cap m", "cap U")
    if ctrl:
        hdr += " | %10s %9s" % ("mkfork fix", "mkfork per")
    print(hdr)
    print("-" * len(hdr))
    fits = {}
    for name in ORDER + sorted(set(mock) - set(ORDER)):
        if name not in mock and name not in usdc:
            continue
        fm = fit(mock[name]) if name in mock else (None, None)
        fu = fit(usdc[name]) if name in usdc else (None, None)
        fits[name] = (fm, fu)
        line = "%-18s %10.0f %9s | %10.0f %9s | %8s %8s | %6s %6s" % (
            name, fm[0], "-" if fm[1] is None else "%.1f" % fm[1], fu[0], "-" if fu[1] is None else "%.1f" % fu[1],
            pct(fm[0], fu[0]), pct(fm[1], fu[1]) if fm[1] else ("   0" if fu[1] == 0 else "  -"),
            cap(*fm) if fm[1] else "-", cap(*fu) if fu[1] else "-")
        if ctrl and name in ctrl:
            fc = fit(ctrl[name])
            line += " | %10.0f %9s" % (fc[0], "-" if fc[1] is None else "%.1f" % fc[1])
        print(line)
    print("\ncap m / cap U: largest m under 2^24 by the mock / USDC fit")
    if ctrl:
        same = all(sorted(ctrl[k]) == sorted(mock[k]) for k in ctrl if k in mock)
        print("mock token on the fork equals the local mock-token rows point for point: %s" % same)

    def g(name, i, which=1):
        return fits[name][which][i]

    print("\nconstants of the P9 cost calculation (p9.py lines 67-82), mock -> USDC:")
    rel = [("REL1_F (inline fixed)", "inline", 0), ("REL1_M (inline per sale)", "inline", 1),
           ("REL_CUR (pass)", "pass", 0), ("REL1_PROVEN fixed", "inline_proven", 0), ("REL1_PROVEN per sale", "inline_proven", 1),
           ("RELU_CHK fixed", "check", 0), ("RELU_CHK per sale", "check", 1), ("RELU_PAY fixed", "payunit", 0), ("RELU_PAY per sale", "payunit", 1),
           ("ANC_UNIT plain fixed", "unit_plain", 0), ("ANC_UNIT plain per leaf", "unit_plain", 1),
           ("ANC_UNIT accepted fixed", "unit_accepted", 0), ("ANC_UNIT accepted per leaf", "unit_accepted", 1),
           ("ANC_COMPLETE plain fixed", "complete_plain", 0), ("ANC_COMPLETE plain per record", "complete_plain", 1),
           ("ANC_COMPLETE marked fixed", "complete_marked", 0), ("ANC_COMPLETE marked per record", "complete_marked", 1),
           ("ANC_COMPLETE accepted fixed", "complete_accepted", 0), ("ANC_COMPLETE accepted per record", "complete_accepted", 1),
           ("ANC_CHUNK plain fixed", "chunk_plain", 0), ("ANC_CHUNK plain per record", "chunk_plain", 1),
           ("ANC_CHUNK marked fixed", "chunk_marked", 0), ("ANC_CHUNK marked per record", "chunk_marked", 1),
           ("ANC_CHUNK accepted fixed", "chunk_accepted", 0), ("ANC_CHUNK accepted per record", "chunk_accepted", 1),
           ("ANC_PULLSALE marked", "pullsale_marked", 0), ("ANC_PULLSALE accepted", "pullsale_accepted", 0)]
    for label, name, i in rel:
        if name not in fits:
            continue
        m_, u_ = g(name, i, 0), g(name, i, 1)
        print("  %-34s %10.0f -> %10.0f  %s" % (label, m_, u_, pct(m_, u_)))
    fu_m = g("check", 0, 0) + g("payunit", 0, 0)
    fu_u = g("check", 0, 1) + g("payunit", 0, 1)
    mu_m = g("check", 1, 0) + g("payunit", 1, 0)
    mu_u = g("check", 1, 1) + g("payunit", 1, 1)
    print("  %-34s %10.0f -> %10.0f  %s" % ("REL FU (check + payunit fixed)", fu_m, fu_u, pct(fu_m, fu_u)))
    print("  %-34s %10.1f -> %10.1f  %s" % ("REL MU (check + payunit per sale)", mu_m, mu_u, pct(mu_m, mu_u)))
    fc1 = lambda w: g("complete_plain", 0, w) + g("unit_accepted", 1, w) - g("unit_plain", 1, w)
    print("  %-34s %10.0f -> %10.0f  %s" % ("ANC FC signed (P9's derived term)", fc1(0), fc1(1), pct(fc1(0), fc1(1))))


if __name__ == "__main__":
    main()
