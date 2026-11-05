#!/usr/bin/env bash
# Runs one P5 test (by name) on a Base mainnet fork pinned at FORK_BLOCK,
# under the p5 profile, one thread, --isolate, and keeps the log and the
# receipts table (label, gas, tx gas, to, calldata) under p5-out/<name>.{log,tsv}.
#   FORK_RPC  upstream RPC to fork from (default: the public Base RPC; read only)
set -euo pipefail
name="$1"; test="$2"
FORK_RPC="${FORK_RPC:-https://mainnet.base.org}"
FORK_BLOCK="${FORK_BLOCK:-52977000}"
cd "$(git rev-parse --show-toplevel)"
mkdir -p g10b-out p5-out
rm -f g10b-out/receipts.tsv
cmd="FOUNDRY_PROFILE=p5 forge test --threads 1 --isolate -vv --fork-url $FORK_RPC --fork-block-number $FORK_BLOCK --match-test $test"
{
  echo "# commit $(git rev-parse --short HEAD)$(git diff --quiet HEAD -- contracts foundry.toml || echo '+dirty')  $(date -u +%FT%TZ)  $(forge --version | head -1)"
  echo "# $cmd"
  FOUNDRY_PROFILE=p5 forge test --threads 1 --isolate -vv --fork-url "$FORK_RPC" --fork-block-number "$FORK_BLOCK" --match-test "$test" 2>&1
} > "p5-out/$name.log"
[ -f g10b-out/receipts.tsv ] && mv g10b-out/receipts.tsv "p5-out/$name.tsv" || true
grep -E "Suite result|FAIL|\[PASS\]" "p5-out/$name.log" || true
