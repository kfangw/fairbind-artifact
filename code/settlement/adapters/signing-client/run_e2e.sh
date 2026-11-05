#!/usr/bin/env bash
# Builds the sdk Foundry profile and runs the end-to-end scenarios on a local
# anvil fork of Base (fork-only keys, no real funds). Needs anvil and forge on
# PATH and node >= 22.18. Result: e2e-out/result.json.
set -euo pipefail
cd "$(dirname "$0")"
(cd ../.. && FOUNDRY_PROFILE=sdk forge build >/dev/null)
[ -d node_modules ] || npm ci
node e2e/run.ts
