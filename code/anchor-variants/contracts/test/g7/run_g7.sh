#!/usr/bin/env bash
# Symbolic checks and concrete cases of the tier 1a and tier 0 verification
# contracts and of the reference contract's proof call.
#
# Run from the repository root with forge (Foundry 1.5.1), halmos (0.3.3) and
# hevm (0.55.1) on PATH, and a z3 binary on PATH for hevm (the one installed
# with halmos works: <halmos tool dir>/bin). Logs go to g7-out/.
#
# hevm reads every artifact under out/, so out/ must hold only the g7
# profile's artifacts (built with --ast); the script removes out/g7 and
# cache/g7 first and fails if another profile's output is present.
#
# Usage: contracts/test/g7/run_g7.sh
set -u
export FOUNDRY_PROFILE=g7
OUT=g7-out
mkdir -p "$OUT"
for d in out/*; do
    [ -e "$d" ] || continue
    [ "$d" = out/g7 ] || { echo "remove $d first (hevm reads all of out/)"; exit 1; }
done
rm -rf out/g7 cache/g7
forge build --ast --extra-output storageLayout metadata > "$OUT/build.log" 2>&1 || { tail -20 "$OUT/build.log"; exit 1; }

strip() { sed 's/\x1b\[[0-9;]*m//g'; }

# halmos: tier 1a and tier 0
FN='check_'
for c in LazerSymbolicTest StorageSymbolicTest; do
    timeout 3600 halmos --forge-build-out out/g7 --match-contract "$c" --function "$FN" \
        --loop 40 --solver-timeout-assertion 300000 > "$OUT/halmos_$c.log" 2>&1
    echo "halmos $c exit $?"
    strip < "$OUT/halmos_$c.log" | grep -E "^\[(PASS|FAIL|ERROR|TIMEOUT)\]|Symbolic test result|NotConcreteError"
done

# hevm: the proof call (the set-up signs with vm.sign, which hevm runs
# concretely; halmos makes the signature symbolic and the set-up branches)
timeout 3600 hevm test --root . --match 'prove_' --solver z3 --max-iterations -1 --smttimeout 300 \
    > "$OUT/hevm_ProveCall.log" 2>&1
echo "hevm ProveCallHevmTest exit $?"
strip < "$OUT/hevm_ProveCall.log" | grep -E "\[(PASS|FAIL)\]|WARNING|->"
rm -f query-*.smt2

# forge: concrete counterexamples, the fuzz case and the concrete
# non-vacuity case of the proof call (separate output directory)
FOUNDRY_OUT=$OUT/forge-out FOUNDRY_CACHE_PATH=$OUT/forge-cache \
    forge test --match-contract 'ConcreteCasesTest|ProveCallHevmTest' --fuzz-runs 10000 > "$OUT/forge_concrete.log" 2>&1
echo "forge exit $?"
grep -E "\[(PASS|FAIL)|Suite result" "$OUT/forge_concrete.log"

# opcodes that read the environment or state, per verification contract
python3 -I contracts/test/g7/scan_opcodes.py out/g7 P5LazerVerifier P5StorageVerifier | tee "$OUT/opcodes.txt"
