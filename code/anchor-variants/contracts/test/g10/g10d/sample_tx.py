#!/usr/bin/env python3
"""Draws the x402 settlement transactions whose receipts M2 reads (G10d-1).

Input: the daily settlement tables of the median and busy windows (columns
block_number, block_time_utc, tx_hash, ..., facilitator). Not committed.

Design, fixed before any receipt was read:
  * days D = every daily file of the given folders, in date order (42 days);
  * facilitators F = the sorted distinct facilitator addresses over all days;
  * budget N = 400; day d gets n_d = floor((d+1)N/|D|) - floor(dN/|D|) cells;
  * the cells of day d are the next n_d facilitators in the sorted order F,
    read cyclically from a running position o that carries over from day to
    day, skipping facilitators with no settlement that day; with all |F|
    active this gives each facilitator about N/|F| cells and each day 9 or
    10 (a first pass that did not skip inactive facilitators left 28 cells
    empty on the four days with 5 active facilitators; fixed before any
    receipt was read);
  * in each (day, facilitator) cell one distinct tx_hash is drawn uniformly
    with random.Random(SEED), hashes sorted before the draw; a hash already
    drawn is skipped (the draw repeats).
Writes one row per drawn hash: window, date, facilitator, hash, block, time,
and how many settlement rows the raw table has for that hash.

Usage: sample_tx.py --seed 20261023 --n 400 --out OUT.tsv DIR [DIR ...]
"""
import argparse
import csv
import glob
import gzip
import os
import random
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--out", required=True)
    ap.add_argument("dirs", nargs="+")
    a = ap.parse_args()
    files = []
    for d in a.dirs:
        for f in sorted(glob.glob(os.path.join(d, "settlements_*.csv.gz"))):
            files.append((os.path.basename(f)[12:22], os.path.basename(os.path.normpath(d)), f))
    files.sort()
    days = []
    facs = set()
    for date, win, f in files:
        by = defaultdict(dict)  # facilitator -> tx_hash -> (block, time, rows)
        for r in csv.DictReader(gzip.open(f, "rt")):
            m = by[r["facilitator"]]
            h = r["tx_hash"]
            if h in m:
                b, t, k = m[h]
                m[h] = (b, t, k + 1)
            else:
                m[h] = (r["block_number"], r["block_time_utc"], 1)
        facs.update(by)
        days.append((date, win, by))
        print(date, win, len(by), sum(len(v) for v in by.values()), flush=True)
    F = sorted(facs)
    D = len(days)
    rng = random.Random(a.seed)
    seen = set()
    o = 0
    with open(a.out, "w") as w:
        w.write("window\tdate\tfacilitator\ttx_hash\tblock\ttime_utc\trows_in_tx\tday_fac_txs\n")
        for d, (date, win, by) in enumerate(days):
            n_d = (d + 1) * a.n // D - d * a.n // D
            active = [f for f in F if by.get(f)]
            for i in range(n_d):
                # walk the global facilitator order from o, skipping
                # facilitators with no settlement that day (wraps if needed)
                while not by.get(F[o % len(F)]):
                    o += 1
                fac = F[o % len(F)]
                o += 1
                pool = sorted(by[fac])
                while True:
                    h = pool[rng.randrange(len(pool))]
                    if h not in seen:
                        break
                seen.add(h)
                b, t, k = by[fac][h]
                w.write(f"{win}\t{date}\t{fac}\t{h}\t{b}\t{t}\t{k}\t{len(pool)}\n")
            if len(active) < len(F):
                print("day", date, "active facilitators", len(active))
    print("facilitators", len(F), "days", D, "drawn", len(seen))


if __name__ == "__main__":
    main()
