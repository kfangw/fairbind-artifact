#!/usr/bin/env bash
# Runs the reproduction tests and stores the combined log.
# Usage: contracts/test/repro/run.sh [log path]
# Environment:
#   REPRO_LOG     log path (default: out/repro/forge.log under the repo root)
#   FOUNDRY_BIN   directory holding forge, prepended to PATH when set
#   FOUNDRY_SOLC  solc binary passed through to forge when set
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG="${1:-${REPRO_LOG:-$ROOT/out/repro/forge.log}}"
if [ -n "${FOUNDRY_BIN:-}" ]; then export PATH="$FOUNDRY_BIN:$PATH"; fi
mkdir -p "$(dirname "$LOG")"
cd "$ROOT"
{
  echo "# started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  forge --version
  if [ -n "${FOUNDRY_SOLC:-}" ]; then "$FOUNDRY_SOLC" --version; fi
  echo "# command: forge test --match-path 'contracts/test/repro/*' -vv"
} > "$LOG"
set +e
forge test --match-path 'contracts/test/repro/*' -vv 2>&1 | tee -a "$LOG"
status=${PIPESTATUS[0]}
set -e
echo "# exit status: $status" >> "$LOG"
exit "$status"
