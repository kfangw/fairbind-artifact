#!/usr/bin/env bash
# G10d: effective gas price of sampled x402 settlements (M2) and a Chainlink
# VRF v2.5 request and fulfillment on a local Base fork (M3).
# RAW = folder of the daily settlement tables (not committed); KEY = file with
# a throwaway VRF secret (hex), used on the fork only and never printed.
set -euo pipefail
RAW="${RAW:?}"; KEY="${KEY:?}"
RPC=https://mainnet.base.org
D=contracts/test/g10/g10d
cd "$(git rev-parse --show-toplevel)"
mkdir -p g10d-out
# M2: sample (no RPC), receipts and base fees (800 public RPC reads), summary
python3 $D/sample_tx.py --seed 20261023 --n 400 --out g10d-out/sample.tsv \
  "$RAW/S1b_median-window" "$RAW/S1b_busy-window" > g10d-out/sample.log
python3 $D/fetch_receipts.py --rpc $RPC --sample g10d-out/sample.tsv \
  --raw g10d-out/receipts_raw.jsonl --out g10d-out/receipts.tsv > g10d-out/fetch.log
python3 $D/analyze_m2.py g10d-out/receipts.tsv > g10d-out/m2_summary.txt
# M3: local fork at the G10b/G10c block, one anvil, minimal consumer
FOUNDRY_PROFILE=g10d forge build
anvil --fork-url $RPC --fork-block-number 52977000 --hardfork osaka --port 8604 \
  --compute-units-per-second 100 --chain-id 8453 > g10d-out/anvil.log 2>&1 &
trap 'kill %1' EXIT
sleep 6
python3 $D/run_vrf.py --rpc http://127.0.0.1:8604 --key "$KEY" --out g10d-out/vrf.tsv \
  --l1rows g10d-out/vrf_l1rows.tsv > g10d-out/vrf.log
# L1 fee inputs at block 52,977,000 from the G10c l1fee.py run (header line)
python3 contracts/test/g10/g10c/l1big.py --params "${L1PARAMS:?}" --out g10d-out/vrf_l1fee.tsv g10d-out/vrf_l1rows.tsv
python3 $D/vrf_cost.py g10d-out/vrf.tsv g10d-out/vrf_l1fee.tsv > g10d-out/vrf_cost.txt
