#!/usr/bin/env bash
# Deploy FairBind on a local Anvil and write a run directory.
#
#   scripts/deploy-local.sh [PROFILE_DOCUMENT] [RUN_DIR]
#
# PROFILE_DOCUMENT defaults to profiles/local-evaluation-v1.json and RUN_DIR to
# a new directory under ${TMPDIR:-/tmp}. With FAIRBIND_RPC_URL set (the scenario
# controller sets it) the script attaches to that loopback Anvil; otherwise it
# starts one on FAIRBIND_ANVIL_PORT (default 8545), records its pid in
# RUN_DIR/anvil.pid and leaves it running. A started Anvil keeps at most 256
# historical states in memory and none on disk (--prune-history 256): mining the
# long deferral and claim windows would otherwise write gigabytes of state
# snapshots under ~/.foundry/anvil/tmp.
#
# Environment:
#   FAIRBIND_RPC_URL            attach to this Anvil instead of starting one
#   FAIRBIND_ANVIL              Anvil binary to start and report (default: anvil on PATH)
#   FAIRBIND_ANVIL_PORT         port of a started Anvil (default 8545)
#   FAIRBIND_ANVIL_ARGS         extra arguments for a started Anvil
#   FAIRBIND_ADMISSION_OVERRIDE 1 deploys the admission override test build
#   FAIRBIND_VERIFIERS          verifiers to register (default and minimum: max minVerifiers)
#   FAIRBIND_BASE_PORT          first loopback port of the service listeners (default 18400)
#   FAIRBIND_ALLOW_DIRTY        1 allows a dirty tree; the report records it
#   FAIRBIND_INFERENCE_MODEL_DIR  local checkpoint; enables the verifiers' inference predicate
#   FAIRBIND_INFERENCE_CONFIG_DIR its configuration manifests (default: the model directory)
#
# Output in RUN_DIR: deploy-report.json (scripts/local_deploy.py), deployment.json
# (addresses, ids, profile ids, chain id, Anvil default test keys of every role),
# manifest.json (schemas/deployment-manifest-v1.schema.json) and
# services/<role>/*.json, one configuration per service.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-$root/profiles/local-evaluation-v1.json}"
run_dir="${2:-}"
if [[ -z "$run_dir" ]]; then
  run_dir="$(mktemp -d "${TMPDIR:-/tmp}/fairbind-local.XXXXXX")"
fi
mkdir -p "$run_dir"
run_dir="$(cd "$run_dir" && pwd)"
profile="$(cd "$(dirname "$profile")" && pwd)/$(basename "$profile")"

anvil_bin="${FAIRBIND_ANVIL:-anvil}"
export FAIRBIND_ANVIL="$anvil_bin"
for tool in "$anvil_bin" cast forge python3; do
  command -v "$tool" >/dev/null || { echo "deploy-local: $tool not found on PATH" >&2; exit 1; }
done
if [[ ! -f "$root/out/FairBind.sol/FairBind.json" || ! -f "$root/out/MockEIP3009Token.sol/MockEIP3009Token.json" ]]; then
  echo "deploy-local: contract artifacts missing; run forge build" >&2
  exit 1
fi

rpc_url="${FAIRBIND_RPC_URL:-}"
if [[ -z "$rpc_url" ]]; then
  port="${FAIRBIND_ANVIL_PORT:-8545}"
  rpc_url="http://127.0.0.1:$port"
  # shellcheck disable=SC2086
  nohup "$anvil_bin" --host 127.0.0.1 --port "$port" --chain-id 31337 --silent --prune-history 256 ${FAIRBIND_ANVIL_ARGS:-} \
    >"$run_dir/anvil.log" 2>&1 &
  echo $! >"$run_dir/anvil.pid"
fi
for _ in $(seq 1 100); do
  if cast chain-id --rpc-url "$rpc_url" >/dev/null 2>&1; then break; fi
  sleep 0.1
done
cast chain-id --rpc-url "$rpc_url" >/dev/null

deploy_args=(--rpc-url "$rpc_url" --output "$run_dir/deploy-report.json" --profile "$profile")
if [[ "${FAIRBIND_ADMISSION_OVERRIDE:-0}" == "1" ]]; then deploy_args+=(--admission-override); fi
if [[ "${FAIRBIND_ALLOW_DIRTY:-0}" == "1" ]]; then deploy_args+=(--allow-dirty); fi

# The router ABI and storage layout of the artifacts must match test-vectors/deployment;
# local_deploy.py then checks that the deployed code equals the artifacts.
python3 "$root/scripts/check_modules.py" >"$run_dir/check-modules.json"
python3 "$root/scripts/local_deploy.py" "${deploy_args[@]}" >/dev/null
python3 "$root/scripts/local_setup.py" --report "$run_dir/deploy-report.json" --profile "$profile" \
  --run-dir "$run_dir" --rpc-url "$rpc_url" --verifiers "${FAIRBIND_VERIFIERS:-0}" \
  --base-port "${FAIRBIND_BASE_PORT:-18400}" \
  --inference-model-dir "${FAIRBIND_INFERENCE_MODEL_DIR:-}" --inference-config-dir "${FAIRBIND_INFERENCE_CONFIG_DIR:-}"
echo "deploy-local: wrote $run_dir/deployment.json" >&2
