#!/usr/bin/env bash
# Runs one G10 test file on the local Base fork (anvil at FORK_RPC, pinned
# FORK_BLOCK) under the g10b profile, one forge process, one thread, and keeps
# the log and the receipts table under g10b-out/<name>.{log,tsv}.
set -euo pipefail
name="$1"; file="$2"
FORK_RPC="${FORK_RPC:-http://127.0.0.1:8602}"
FORK_BLOCK="${FORK_BLOCK:-52977000}"
# EVM=cancun reruns the same file under the earlier G10 rules (same bytecode).
extra=()
[ -n "${EVM:-}" ] && extra=(--evm-version "$EVM")
cd "$(git rev-parse --show-toplevel)"
mkdir -p g10b-out
rm -f g10b-out/receipts.tsv
cmd="FOUNDRY_PROFILE=g10b forge test --threads 1 --isolate -vv --fork-url $FORK_RPC --fork-block-number $FORK_BLOCK --match-path $file ${extra[*]:-}"
{
  echo "# commit $(git rev-parse --short HEAD)$(git diff --quiet || echo '+dirty')  $(date -u +%FT%TZ)"
  echo "# $cmd"
  FOUNDRY_PROFILE=g10b forge test --threads 1 --isolate -vv --fork-url "$FORK_RPC" --fork-block-number "$FORK_BLOCK" --match-path "$file" "${extra[@]}" 2>&1
} > "g10b-out/$name.log"
[ -f g10b-out/receipts.tsv ] && mv g10b-out/receipts.tsv "g10b-out/$name.tsv" || true
grep -E "Suite result|FAIL" "g10b-out/$name.log" || true
