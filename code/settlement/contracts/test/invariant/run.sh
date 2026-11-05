#!/usr/bin/env bash
# Runs the stateful invariant suite under both freeze timings and the negative
# invariant on the mutation build, and stores the combined log.
#   1. forge test --match-path 'contracts/test/invariant/*'  must pass
#      (freezeOnInitialFail = true on the admission-override build).
#   2. FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path ...  must pass
#      (freezeOnInitialFail = false on the production build, ADR 0020).
#   2b. FAIRBIND_TIERED=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path ...
#      must pass (the profile carries design 2 terms; setBondTerms changes caps,
#      ADR 0024 and ADR 0025).
#   2c. FAIRBIND_TIERED=1 FAIRBIND_UNIT_BOND=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0
#      forge test --match-path ...  must pass (the B = b configuration of
#      decision 131: one prefunded failure and no sanction limit, ADR 0027).
#   3. FAIRBIND_MUTATION=1 forge test --match-contract FreezeMutationInvariantTest
#      must fail: without the bond-level freeze the fuzzer finds a sequence in
#      which a failing seller receives principal settled before its failure.
#   4. FAIRBIND_REENTRY_MUTATION=1 forge test --match-contract ReentryMutationInvariantTest
#      must fail for the same reason: with the old early return of _freeze
#      during an open claim window (ADR 0021), a purchase settled after a
#      reinstatement stays outside the frozen window at the next confirmed
#      failure and is released to the failing seller.
#   5. FAIRBIND_WAIT_MUTATION=1 forge test --match-contract WaitReleaseMutationInvariantTest
#      must fail: when a case waiting for an assignment does not hold its
#      purchase (ADR 0028), the fuzzer releases that purchase to the seller.
#   6. FAIRBIND_PAUSE_MUTATION=1 forge test --match-contract PauseIgnoredMutationInvariantTest
#      must fail: when release counts the blocks in which a case of the
#      account waited (ADR 0029), the fuzzer releases an entry before
#      deferBlocks unpaused blocks since its settlement.
#   7. FAIRBIND_WIDE_FREEZE_MUTATION=1 forge test --match-contract WideFreezeMutationInvariantTest
#      must fail: when a confirmed failure freezes from block zero instead of
#      the failing sale (ADR 0030), an entry settled before the sale is frozen.
# Steps 3 to 7 depend on the fuzz seed, which forge draws anew on each run.
# Before the scenario actions failThenRelease (step 3), reenter with mode bit 1
# (step 4) and waitThenRelease (steps 5 and 6), one campaign in eight to one
# in four of each step ended without its violation; with them every campaign
# of sixteen fixed seeds found it.
# Steps 1 to 2c include WaitingAssignmentInvariantTest and WaitingCoverageTest,
# the waiting-assignment variant of the suite (ADR 0028), and the release-clock
# invariant (ADR 0029).
# Exit status 0 only when all nine expectations hold.
# Usage: contracts/test/invariant/run.sh [log path]
# Environment:
#   INVARIANT_LOG  log path (default: out/invariant/forge.log under the repo root)
#   FOUNDRY_BIN    directory holding forge, prepended to PATH when set
#   FOUNDRY_SOLC   solc binary passed through to forge when set
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG="${1:-${INVARIANT_LOG:-$ROOT/out/invariant/forge.log}}"
if [ -n "${FOUNDRY_BIN:-}" ]; then export PATH="$FOUNDRY_BIN:$PATH"; fi
mkdir -p "$(dirname "$LOG")"
cd "$ROOT"
{
  echo "# started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  forge --version
  if [ -n "${FOUNDRY_SOLC:-}" ]; then "$FOUNDRY_SOLC" --version; fi
} > "$LOG"

set +e
echo "# command: forge test --match-path 'contracts/test/invariant/*' -vv" >> "$LOG"
start=$(date +%s)
forge test --match-path 'contracts/test/invariant/*' -vv 2>&1 | tee -a "$LOG"
real=${PIPESTATUS[0]}
echo "# exit status: $real, seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv" >> "$LOG"
start=$(date +%s)
FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv 2>&1 | tee -a "$LOG"
production=${PIPESTATUS[0]}
echo "# exit status: $production, seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_TIERED=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv" >> "$LOG"
start=$(date +%s)
FAIRBIND_TIERED=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv 2>&1 | tee -a "$LOG"
tiered=${PIPESTATUS[0]}
echo "# exit status: $tiered, seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_TIERED=1 FAIRBIND_UNIT_BOND=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv" >> "$LOG"
start=$(date +%s)
FAIRBIND_TIERED=1 FAIRBIND_UNIT_BOND=1 FAIRBIND_FREEZE_ON_INITIAL_FAIL=0 forge test --match-path 'contracts/test/invariant/*' -vv 2>&1 | tee -a "$LOG"
unitbond=${PIPESTATUS[0]}
echo "# exit status: $unitbond, seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_MUTATION=1 forge test --match-contract FreezeMutationInvariantTest -vv" >> "$LOG"
start=$(date +%s)
FAIRBIND_MUTATION=1 forge test --match-contract FreezeMutationInvariantTest -vv 2>&1 | tee -a "$LOG"
mutation=${PIPESTATUS[0]}
echo "# exit status: $mutation (a failure is expected), seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_REENTRY_MUTATION=1 forge test --match-contract ReentryMutationInvariantTest -vv" >> "$LOG"
start=$(date +%s)
REENTRY_OUT="$(dirname "$LOG")/reentry-mutation.log"
FAIRBIND_REENTRY_MUTATION=1 forge test --match-contract ReentryMutationInvariantTest -vv 2>&1 | tee "$REENTRY_OUT" | tee -a "$LOG"
reentry=${PIPESTATUS[0]}
echo "# exit status: $reentry (a failure is expected), seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_WAIT_MUTATION=1 forge test --match-contract WaitReleaseMutationInvariantTest -vv" >> "$LOG"
start=$(date +%s)
WAIT_OUT="$(dirname "$LOG")/wait-mutation.log"
FAIRBIND_WAIT_MUTATION=1 forge test --match-contract WaitReleaseMutationInvariantTest -vv 2>&1 | tee "$WAIT_OUT" | tee -a "$LOG"
waitmut=${PIPESTATUS[0]}
echo "# exit status: $waitmut (a failure is expected), seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_PAUSE_MUTATION=1 forge test --match-contract PauseIgnoredMutationInvariantTest -vv" >> "$LOG"
start=$(date +%s)
PAUSE_OUT="$(dirname "$LOG")/pause-mutation.log"
FAIRBIND_PAUSE_MUTATION=1 forge test --match-contract PauseIgnoredMutationInvariantTest -vv 2>&1 | tee "$PAUSE_OUT" | tee -a "$LOG"
pausemut=${PIPESTATUS[0]}
echo "# exit status: $pausemut (a failure is expected), seconds: $(( $(date +%s) - start ))" >> "$LOG"

echo "# command: FAIRBIND_WIDE_FREEZE_MUTATION=1 forge test --match-contract '^WideFreezeMutationInvariantTest$' -vv" >> "$LOG"
start=$(date +%s)
WIDE_OUT="$(dirname "$LOG")/wide-freeze-mutation.log"
FAIRBIND_WIDE_FREEZE_MUTATION=1 forge test --match-contract '^WideFreezeMutationInvariantTest$' -vv 2>&1 | tee "$WIDE_OUT" | tee -a "$LOG"
widemut=${PIPESTATUS[0]}
echo "# exit status: $widemut (a failure is expected), seconds: $(( $(date +%s) - start ))" >> "$LOG"
set -e

if [ "$real" -ne 0 ]; then
  echo "# result: invariant suite failed" >> "$LOG"
  exit 1
fi
if [ "$production" -ne 0 ]; then
  echo "# result: invariant suite failed on the production build (freezeOnInitialFail = false)" >> "$LOG"
  exit 1
fi
if [ "$tiered" -ne 0 ]; then
  echo "# result: invariant suite failed under design 2 terms" >> "$LOG"
  exit 1
fi
if [ "$unitbond" -ne 0 ]; then
  echo "# result: invariant suite failed under design 2 terms with B = b" >> "$LOG"
  exit 1
fi
if [ "$mutation" -eq 0 ]; then
  echo "# result: the mutation build passed the negative invariant; the invariant no longer detects the leak" >> "$LOG"
  exit 1
fi
if ! grep -q "released to the seller after a final failure" "$LOG"; then
  echo "# result: the mutation run failed for another reason than the leak" >> "$LOG"
  exit 1
fi
if [ "$reentry" -eq 0 ]; then
  echo "# result: the re-entry mutation build passed the negative invariant; the invariant no longer detects the leak" >> "$LOG"
  exit 1
fi
if ! grep -q "released to the seller after a final failure" "$REENTRY_OUT"; then
  echo "# result: the re-entry mutation run failed for another reason than the leak" >> "$LOG"
  exit 1
fi
if [ "$waitmut" -eq 0 ]; then
  echo "# result: the waiting-release mutation build passed the release invariant; the invariant no longer detects it" >> "$LOG"
  exit 1
fi
if ! grep -q "released while its case waits for an assignment" "$WAIT_OUT"; then
  echo "# result: the waiting-release mutation run failed for another reason than the release" >> "$LOG"
  exit 1
fi
if [ "$pausemut" -eq 0 ]; then
  echo "# result: the release-clock mutation build passed the release invariant; the invariant no longer detects it" >> "$LOG"
  exit 1
fi
if ! grep -q "released before deferBlocks unpaused blocks" "$PAUSE_OUT"; then
  echo "# result: the release-clock mutation run failed for another reason than the release" >> "$LOG"
  exit 1
fi
if [ "$widemut" -eq 0 ]; then
  echo "# result: the wide-freeze mutation build passed; the suite no longer detects a freeze before the failing sale" >> "$LOG"
  exit 1
fi
if ! grep -q "before the start" "$WIDE_OUT"; then
  echo "# result: the wide-freeze mutation run failed for another reason than the wide freeze" >> "$LOG"
  exit 1
fi
echo "# result: suite passed under both freeze timings, both design 2 bond configurations, and all five mutation builds were rejected" >> "$LOG"
