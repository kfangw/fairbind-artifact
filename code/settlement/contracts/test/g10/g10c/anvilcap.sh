#!/usr/bin/env bash
# Does the local anvil fork (--hardfork osaka) enforce the EIP-7825 cap?
# Sends two plain transfers from a throwaway fork-only key (read from
# KEY_FILE, never printed) with gas limits 2^24 and 2^24 + 1.
set -euo pipefail
R="${FORK_RPC:-http://127.0.0.1:8603}"
K="$(cat "$KEY_FILE")"
A="$(cast wallet address --private-key "$K")"
cast rpc anvil_setBalance "$A" 0x56BC75E2D63100000 --rpc-url "$R" > /dev/null
for g in 16777216 16777217; do
  out=$(cast send 0x000000000000000000000000000000000000bEEF --gas-limit "$g" --private-key "$K" --rpc-url "$R" \
        --gas-price 10000000 --priority-gas-price 1000000 --json 2>&1 || true)
  echo "gas limit $g: $(echo "$out" | python3 -c 'import sys,json
t=sys.stdin.read()
try:
    d=json.loads(t); print("mined, status", d["status"], "gasUsed", int(d["gasUsed"],16))
except Exception:
    print("rejected:", t.strip()[:200])')"
done
