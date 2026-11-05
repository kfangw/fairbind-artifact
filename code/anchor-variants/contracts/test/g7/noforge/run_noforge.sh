#!/usr/bin/env bash
# G7 2nd ed.: the symbolic checks (halmos) and the concrete cases without
# Foundry and hevm. solc-js 0.8.24 builds forge-shaped artifacts (via_ir,
# optimizer 200, cancun: the bytecode forge 1.5.1 builds for the g7
# profile, since solc 0.8.24 has no osaka target), a stand-in `forge`
# that does nothing lets halmos read them, and py-evm runs the concrete
# cases on the old (c5325ca) and fixed verification contracts.
#
# needs: node with `npm install solc@0.8.24` (NODE_PATH pointing at its
# node_modules), python with halmos==0.3.3 py-evm trie rlp eth-abi eth-keys
# "eth-hash[pycryptodome]" (PY, default python3). Run from the repository
# root. Output in g7-out-noforge/. About 10 minutes on 4 cores.
#
# usage: contracts/test/g7/noforge/run_noforge.sh
set -eu
PY="${PY:-python3}"
HALMOS="${HALMOS:-halmos}"
HERE=contracts/test/g7/noforge
OUT="$PWD/g7-out-noforge"
rm -rf "$OUT" && mkdir -p "$OUT/bin" "$OUT/old"
cp "$HERE/forge" "$OUT/bin/forge" && chmod +x "$OUT/bin/forge"
export PATH="$OUT/bin:$PATH"
build() { # <root> <json> <name> <files...>
    local root=$1 json=$2 dir=$3; shift 3
    (cd "$root" && node "$OLDPWD/$HERE/compile.js" . "$json" "$@")
    rm -rf "$dir" && $PY -I "$HERE/toforge.py" "$json" "$dir"
}
git archive c5325ca contracts | tar -x -C "$OUT/old"
build "$OUT/old" "$OUT/old_verifiers.json" "$OUT/art_old" contracts/test/g10/p5/P5Verifiers.sol
build . "$OUT/new_verifiers.json" "$OUT/art_new" contracts/test/g10/p5/P5Verifiers.sol
{ echo "== c5325ca"; $PY -I contracts/test/g7/scan_opcodes.py "$OUT/art_old" P5LazerVerifier P5StorageVerifier
  echo "== this tree"; $PY -I contracts/test/g7/scan_opcodes.py "$OUT/art_new" P5LazerVerifier P5StorageVerifier; } | tee "$OUT/opcodes.txt"
# symbolic checks on the fixed contracts
mkdir -p "$OUT/h_new" && build . "$OUT/sym_new.json" "$OUT/h_new/out" \
    contracts/test/g7/LazerSymbolic.t.sol contracts/test/g7/StorageSymbolic.t.sol
# the same checks on the c5325ca contracts (before the fix); P5Slot is
# appended to the old file only so that StorageSymbolic compiles
cp contracts/test/g7/{LazerSymbolic.t.sol,StorageSymbolic.t.sol,SyntheticHistoryFixture.sol} "$OUT/old/contracts/test/g7/"
sed -n '/^\/\/\/ A storage slot value/,$p' contracts/test/g10/p5/P5Verifiers.sol >> "$OUT/old/contracts/test/g10/p5/P5Verifiers.sol"
mkdir -p "$OUT/h_old" && build "$OUT/old" "$OUT/sym_old.json" "$OUT/h_old/out" \
    contracts/test/g7/LazerSymbolic.t.sol contracts/test/g7/StorageSymbolic.t.sol
for side in new old; do
    for c in LazerSymbolicTest StorageSymbolicTest; do
        (cd "$OUT/h_$side" && timeout 3600 $HALMOS --root . --forge-build-out out --match-contract $c --function check_ \
            --loop 40 --solver-timeout-assertion 300000 > "$OUT/halmos_${side}_$c.log" 2>&1) || true
        echo "halmos ($side contracts) $c"
        sed 's/\x1b\[[0-9;]*m//g' "$OUT/halmos_${side}_$c.log" | grep -E "^\[(PASS|FAIL|ERROR|TIMEOUT)\]|Symbolic test result" \
            | grep -v total40 || true
        echo "  check_V1to4_total40_lenNN PASS: $(grep -c 'PASS.*total40' "$OUT/halmos_${side}_$c.log" || true)"
    done
done | tee "$OUT/halmos.txt"
# concrete cases (py-evm)
$PY -I contracts/test/g7/gen_synthetic_fixture.py "$OUT/SyntheticHistoryFixture.sol" "$OUT/synth.json"
cmp "$OUT/SyntheticHistoryFixture.sol" contracts/test/g7/SyntheticHistoryFixture.sol && echo "fixture reproduced"
PYTHONPATH="$HERE" $PY "$HERE/cases.py" "$OUT" "$OUT/synth.json" | tee "$OUT/cases.txt"
