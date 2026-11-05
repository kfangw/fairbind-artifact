#!/usr/bin/env python3
"""Check a directory of daily settlement files against its manifest.jsonl.

usage: python3 verify_raw.py <manifest.jsonl> <directory with settlements_YYYY-MM-DD.csv.gz>
For every manifest line it checks that the file exists and that its byte size and SHA-256 equal
bytes_gz and sha256_gz. It does not parse the rows (chain_inputs.py build does that and checks
row counts and value sums). Exit status 0 only if every file matches.
"""
import hashlib, json, os, sys

manifest, folder = sys.argv[1], sys.argv[2]
bad = 0
n = 0
for line in open(manifest, encoding="utf-8"):
    if not line.strip():
        continue
    m = json.loads(line)
    p = os.path.join(folder, m["file"])
    n += 1
    if not os.path.exists(p):
        print("MISSING", m["file"]); bad += 1; continue
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if os.path.getsize(p) != m["bytes_gz"] or h.hexdigest() != m["sha256_gz"]:
        print("DIFFERS", m["file"]); bad += 1
print(f"{n} files listed, {bad} problems")
sys.exit(1 if bad else 0)
