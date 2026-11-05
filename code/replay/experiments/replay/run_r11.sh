#!/bin/bash
# R11: replay of rule edition 10 candidate as written (registration R11_preregistration.md in the research repository).
#   bash experiments/replay/run_r11.sh gate       # G0 only: sealed registration hash, its commit on origin/main
#   bash experiments/replay/run_r11.sh prepare    # code, environment, tests, input hashes, lists (no replay)
#   nohup bash experiments/replay/run_r11.sh run > /dev/null 2>&1 &    # G0, replays, fraud replays, aggregation
#   bash experiments/replay/run_r11.sh status
# Every step leaves $SCRATCH/done/<step>; a repeated call skips finished steps, configurations and replicates.
# Raw outputs (with sales.npz, which stays out of git) go to $SCRATCH/raw, the aggregation to $SCRATCH/summary.
# Copying the aggregation into the research repository (docs/11_journal/R11/results/) and committing it is done by hand.
set -euo pipefail
RESEARCH="${RESEARCH:-./research-clone}"      # clone of the research repository (registration, inputs)
SCRATCH="${SCRATCH:-./scratch}"
RAWDATA="${RAWDATA:-./raw-data}"
PARALLEL="${PARALLEL:-2}"           # replay configurations at the same time (a busy-window run needs about 5 GB)
JOBS="${JOBS:-4}"                   # fraud replay workers (about 2 GB each)
R="${R:-500}"                       # fraud replay replicates (registration 4.5: 500)
ANCHOR_DELAY="${ANCHOR_DELAY:-120}" # a_A of v0.7c (registration 4.2); the R10-equivalent variant uses 100
KS="${KS:-1,2,3,6}"
DOCS="$RESEARCH/docs"
R11="$DOCS/11_journal/R11"
REG="$R11/R11_preregistration.md"
REG_REL="docs/11_journal/R11/R11_preregistration.md"
RAW="$SCRATCH/raw"; SUM="$SCRATCH/summary"; LOGS="$SCRATCH/logs"; DONE="$SCRATCH/done"
REPO="$SCRATCH/replayer"; VENV="$SCRATCH/.venv"; LISTS="$RAW/lists"
CODE_URL="${CODE_URL:-https://example.org/fairbind-code.git}"
CODE_BRANCH="${CODE_BRANCH:-r11-replay}"
EXPECT_HEAD="${EXPECT_HEAD:-SET-AT-SEAL}"   # registration 2.4: the replayer commit; passed in the environment, must appear in the sealed file

MAN_MED_SHA=1f48d314055fa8bf0e92cb8e118975287d55f4ab7ac0a917e0e1104922e84923
MAN_BUSY_SHA=90371183d2bfcad691db4ab7d886754010f876eda4e794f72ca0ff55bc72d7e1
LIST_MED_SHA=091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a
LIST_BUSY_SHA=91412e264212412afcd4ecdd21e7ca7d98ce7ab8522572fdabef756e6fa10133
LIST_MED=settlements_base_2026-07-24_2026-08-13.csv
LIST_BUSY=settlements_base_2026-06-09_2026-06-29.csv
COND_MED="$DOCS/05_run-evidence/design2/median-period/in/conditions_base_median.json"
COND_MED_SHA=5e58da679e9dcf8d04ab0f750d955cde95156a66900b910e614f42840ac56e8c
COND_BUSY="$DOCS/11_journal/J9/in/conditions_base_busy.json"
COND_BUSY_SHA=b55539d65c52addd93a79e994c041ad4370a626f506423f91d4017d5a3481936
REF="$DOCS/11_journal/J9/in/ref"
TOP_SHA=3f255ef8174bf502cbc1f7d14e6ec84a011f6d5e8599779b11cd04e5c9bcae91
ALL_SHA=bb7ee6f57f87b990b665fb65739b1bae32c14cc98b5852b079dd625d9d53b124
D2CFG="$DOCS/11_journal/J13a/in/design2_vmax05.json"
D2CFG_SHA=76cf20c6423a108c555b80b70c8d1ddcf05c336bd14eeb5ef5631d8132a77caf

mkdir -p "$RAW" "$SUM" "$LOGS" "$DONE" "$LISTS"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
say() { echo "[$(date -u '+%F %T')Z] $*" | tee -a "$LOGS/run.log"; }
die() { say "stopped: $*"; st "stopped: $*"; exit 1; }
st() { printf '{"phase": "%s", "time_utc": "%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$SCRATCH/status.json"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
check_sha() { [ -e "$1" ] || die "missing: $1"; local g; g="$(sha "$1")"; [ "$g" = "$2" ] || die "hash differs: $1 ($g, expected $2)"; }
done_mark() { date -u +%FT%TZ > "$DONE/$1"; }
is_done() { [ -f "$DONE/$1" ]; }

if [ "${1:-}" = "status" ]; then
  cat "$SCRATCH/status.json" 2>/dev/null || echo "not started"
  ls "$DONE" 2>/dev/null | tr '\n' ' '; echo
  tail -n 8 "$LOGS/run.log" 2>/dev/null || true
  for d in deter deter_r10style; do [ -f "$RAW/$d/status.json" ] && cat "$RAW/$d/status.json"; done
  exit 0
fi

# ---------------------------------------------------------------- G0: the sealed registration is on origin/main
gate0() {
  [ -f "$REG" ] || die "G0: registration $REG missing (seal first: registration section 10)"
  [ -f "$REG.sha256" ] || [ -f "${REG%.md}.sha256" ] || die "G0: R11_preregistration.sha256 missing"
  local SHAFILE="${REG%.md}.sha256"
  local WANT; WANT="$(awk '{print $1; exit}' "$SHAFILE")"
  [ "${#WANT}" -eq 64 ] || die "G0: $SHAFILE has no SHA-256 in its first word"
  check_sha "$REG" "$WANT"
  # The commit that carries the sealed file must be on origin/main, and origin/main must still carry exactly it.
  local REMOTE_HEAD
  REMOTE_HEAD="$(git -C "$RESEARCH" ls-remote origin refs/heads/main | cut -f1)"
  [ "${#REMOTE_HEAD}" -eq 64 ] || [ "${#REMOTE_HEAD}" -eq 40 ] || die "G0: git ls-remote origin main gave nothing"
  git -C "$RESEARCH" fetch -q origin "$REMOTE_HEAD" || git -C "$RESEARCH" fetch -q origin main || die "G0: fetch failed"
  local REMOTE_REG REMOTE_STATED
  REMOTE_REG="$(git -C "$RESEARCH" cat-file blob "$REMOTE_HEAD:$REG_REL" | sha256sum | cut -d' ' -f1)" \
    || die "G0: $REG_REL is not in origin/main ($REMOTE_HEAD)"
  [ "$REMOTE_REG" = "$WANT" ] || die "G0: origin/main carries a registration with hash $REMOTE_REG, not the sealed $WANT"
  REMOTE_STATED="$(git -C "$RESEARCH" cat-file blob "$REMOTE_HEAD:${REG_REL%.md}.sha256" | awk '{print $1; exit}')" \
    || die "G0: the .sha256 file is not in origin/main"
  [ "$REMOTE_STATED" = "$WANT" ] || die "G0: origin/main's .sha256 says $REMOTE_STATED, not $WANT"
  [ "$EXPECT_HEAD" != "SET-AT-SEAL" ] && [ "${#EXPECT_HEAD}" -eq 40 ] || die "G0: EXPECT_HEAD (replayer commit, registration 2.4) is not set"
  grep -q "$EXPECT_HEAD" "$REG" || die "G0: the sealed registration does not name the replayer commit $EXPECT_HEAD (section 2.4)"
  printf '{"registration_sha256": "%s", "origin_main": "%s", "replayer_commit": "%s", "checked_utc": "%s"}\n' \
    "$WANT" "$REMOTE_HEAD" "$EXPECT_HEAD" "$(date -u +%FT%TZ)" > "$SUM/g0.json"
  say "G0: registration $WANT is on origin/main $REMOTE_HEAD; replayer $EXPECT_HEAD"
}

# ---------------------------------------------------------------- prepare: no replay
prepare() {
  st "prepare"
  [ "$EXPECT_HEAD" != "SET-AT-SEAL" ] || die "EXPECT_HEAD is not set (registration 2.4)"
  if [ ! -d "$REPO/.git" ]; then git clone -q "$CODE_URL" "$REPO"; fi
  git -C "$REPO" fetch -q origin "$CODE_BRANCH" || die "cannot fetch the code branch $CODE_BRANCH"
  git -C "$REPO" checkout -q --detach "$EXPECT_HEAD" || die "commit $EXPECT_HEAD is missing"
  [ -z "$(git -C "$REPO" status --porcelain)" ] || die "the replayer tree is not clean"
  say "replayer $EXPECT_HEAD, clean tree"
  if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV" && "$VENV/bin/pip" install -q --upgrade pip && "$VENV/bin/pip" install -q numpy scipy \
      || die "cannot build the Python environment"
  fi
  "$VENV/bin/python" -c "import numpy, scipy, sys; print('python', sys.version.split()[0], 'numpy', numpy.__version__, 'scipy', scipy.__version__)" | tee -a "$LOGS/run.log"
  if ! is_done tests; then
    (cd "$REPO/experiments/replay" && for t in test_r11 test_r11_compute test_release10 test_release10_bruteforce test_release8; do
       "$VENV/bin/python" -m unittest "$t" || exit 1; done) > "$LOGS/tests.log" 2>&1 || die "replayer tests failed ($LOGS/tests.log)"
    done_mark tests; say "tests passed ($(grep -cE '^OK' "$LOGS/tests.log") suites)"
  fi
  check_sha "$RAWDATA/S1b_median-window/manifest.jsonl" "$MAN_MED_SHA"
  check_sha "$RAWDATA/S1b_busy-window/manifest.jsonl" "$MAN_BUSY_SHA"
  check_sha "$COND_MED" "$COND_MED_SHA"; check_sha "$COND_BUSY" "$COND_BUSY_SHA"
  check_sha "$REF/sellers_dune_top400.csv" "$TOP_SHA"; check_sha "$REF/sellers_dune_all4400.csv" "$ALL_SHA"
  check_sha "$D2CFG" "$D2CFG_SHA"
  for W in median busy; do
    if [ "$W" = median ]; then DIR="$RAWDATA/S1b_median-window"; F=$LIST_MED; WANT=$LIST_MED_SHA
    else DIR="$RAWDATA/S1b_busy-window"; F=$LIST_BUSY; WANT=$LIST_BUSY_SHA; fi
    if [ ! -f "$LISTS/$W/$F" ] || [ "$(sha "$LISTS/$W/$F")" != "$WANT" ]; then
      say "building the list ($W)"
      (cd "$REPO/experiments/replay" && "$VENV/bin/python" chain_inputs.py build --chain base --dir "$DIR" --out "$LISTS/$W") \
        >> "$LOGS/lists.log" 2>&1 || die "chain_inputs build failed ($W)"
    fi
    check_sha "$LISTS/$W/$F" "$WANT"
  done
  done_mark prepare
  say "prepare finished: both lists verified"
}

list_of() { if [ "$1" = median ]; then echo "$LISTS/median/$LIST_MED"; else echo "$LISTS/busy/$LIST_BUSY"; fi; }
cond_of() { if [ "$1" = median ]; then echo "$COND_MED"; else echo "$COND_BUSY"; fi; }
COMMON=(--k-w 0.015 --d2-config "$D2CFG" --preset r11-main)

# ---------------------------------------------------------------- one replay configuration (d2_sweep; finished ones skipped)
replay_cfg() {   # name window mode Vlist [replay.py arguments...]
  local name="$1" W="$2" MODE="$3" VLIST="$4"; shift 4
  local key="replay_${name}_${W}"
  is_done "$key" && return 0
  local SUFFIX=""; [ "$name" != main ] && SUFFIX="_$name"
  local par=1; [ "$name" = main ] && par="$PARALLEL"
  local rc=1 attempt
  for attempt in 1 2; do
    say "replay $name $W (mode $MODE, V $VLIST) attempt $attempt"
    set +e
    (cd "$REPO" && "$VENV/bin/python" experiments/replay/d2_sweep.py --chain base --vmax "$VLIST" --modes "$MODE" \
      --draws 1 --settlements "$(list_of "$W")" --reference-dir "$REF" --conditions-file "$(cond_of "$W")" \
      --out "$RAW/$W$SUFFIX" --parallel "$par" -- "${COMMON[@]}" "$@") >> "$LOGS/replay_${name}_${W}.log" 2>&1
    rc=$?
    set -e
    [ $rc -eq 0 ] && break
  done
  [ $rc -eq 0 ] || { say "replay $name $W failed (rc=$rc, $LOGS/replay_${name}_${W}.log)"; return 1; }
  done_mark "$key"; say "replay $name $W finished"
}

k_sweep() {   # window
  local W="$1" key="ksweep_$1"
  is_done "$key" && return 0
  say "k sweep $W (k = $KS)"
  (cd "$REPO/experiments/replay" && "$VENV/bin/python" r11_k_sweep.py --k "$KS" --out "$RAW/${W}_ksweep" -- \
    --settlements "$(list_of "$W")" --conditions-file "$(cond_of "$W")" --reference-dir "$REF" --qx 137 --conditions 1 \
    --repetitions 1 --design 2 --vmax 0.2 --sales-cap none --chain base --draws 1 "${COMMON[@]}" \
    --r10-anchor-delay "$ANCHOR_DELAY") >> "$LOGS/ksweep_${W}.log" 2>&1 || { say "k sweep $W failed"; return 1; }
  done_mark "$key"; say "k sweep $W finished"
}

fraud() {   # name directory [r10_deter.py run arguments...]
  local name="$1" DIR="$2"; shift 2
  is_done "fraud_$name" && return 0
  st "fraud replay $name (R=$R, jobs $JOBS)"
  say "fraud replay $name (R $R, workers $JOBS)"
  (cd "$REPO" && "$VENV/bin/python" experiments/replay/r10_deter.py run --settlements "$(list_of median)" \
    --reference-dir "$REF" --conditions-file "$COND_MED" --out "$RAW/$DIR" --replicates "$R" --jobs "$JOBS" \
    --registered-list-sha256 "$LIST_MED_SHA" "$@") >> "$LOGS/fraud_$name.log" 2>&1 || die "fraud replay $name failed"
  (cd "$REPO" && "$VENV/bin/python" experiments/replay/r10_deter.py analyze --out "$RAW/$DIR" --replicates "$R") \
    > "$LOGS/fraud_${name}_analyze.log" 2>&1 || die "fraud replay $name analysis failed"
  done_mark "fraud_$name"; say "fraud replay $name finished"
}

run_all() {
  st "gate"
  gate0
  is_done prepare || prepare
  # 1. main setting: both windows, four V (a = 0), the V values in parallel
  st "replay main"
  replay_cfg main median none 0.1,0.2,0.5,1 --r10-anchor-delay "$ANCHOR_DELAY" || die "replay main median"
  replay_cfg main busy none 0.1,0.2,0.5,1 --r10-anchor-delay "$ANCHOR_DELAY" || die "replay main busy"
  # 2. acceptance, sensitivities, the legacy bucket, the dispute origin and the R10-equivalent variant (V 0.2)
  st "replay acceptance, sensitivities, variants"
  local specs=(
    "a05|none|--r10-anchor-delay $ANCHOR_DELAY --r10-accept-ppm 500000"
    "a09|none|--r10-anchor-delay $ANCHOR_DELAY --r10-accept-ppm 900000"
    "short|none|--r10-anchor-delay $ANCHOR_DELAY --r10-proof-window 300 --r10-dispute-window 300"
    "long|none|--r10-anchor-delay $ANCHOR_DELAY --r10-proof-window 7200 --r10-dispute-window 7200"
    "u05a09|none|--r10-anchor-delay $ANCHOR_DELAY --r10-accept-ppm 900000 --r10-unsigned-ppm 500000"
    "legacy|auto-zero-reject|--r10-anchor-delay $ANCHOR_DELAY"
    "dsettle|none|--r10-anchor-delay $ANCHOR_DELAY --r10-dispute-from settlement"
    "r10equiv|auto-zero-reject|--r10-anchor-delay 100 --r10-dispute-from settlement"
  )
  local pids=() fail=0 s W name mode args
  for s in "${specs[@]}"; do
    name="${s%%|*}"; mode="$(echo "$s" | cut -d'|' -f2)"; args="${s##*|}"
    for W in median busy; do
      # shellcheck disable=SC2086
      replay_cfg "$name" "$W" "$mode" 0.2 $args &
      pids+=($!)
      if [ "${#pids[@]}" -ge "$PARALLEL" ]; then wait "${pids[0]}" || fail=1; pids=("${pids[@]:1}"); fi
    done
  done
  for p in "${pids[@]}"; do wait "$p" || fail=1; done
  [ $fail -eq 0 ] || die "a sensitivity replay failed (a repeated call skips the finished ones)"
  # 3. k sweep (V 0.2, both windows), two at a time at most
  st "k sweep"
  k_sweep median & local p1=$!
  if [ "$PARALLEL" -ge 2 ]; then k_sweep busy & local p2=$!; wait $p1 || die "k sweep median"; wait $p2 || die "k sweep busy"
  else wait $p1 || die "k sweep median"; k_sweep busy || die "k sweep busy"; fi
  # 4. fraud replays: the main setting, then the R10-style variant (secondary)
  fraud main deter --sales-cap none --accept-over-cap --dispute-from anchor --seller-epoch-k 1 --anchor-delay "$ANCHOR_DELAY"
  fraud r10style deter_r10style --sales-cap auto-zero-reject --dispute-from settlement --seller-epoch-k 1 --anchor-delay 100
  # 5. aggregation (G0 to G6 inside; sales.npz hashes recorded, the files stay in $RAW)
  st "aggregate"
  "$VENV/bin/python" -I "$REPO/experiments/replay/r11_compute.py" --raw "$RAW" --lists "$LISTS" --out "$SUM" \
    --code-commit "$EXPECT_HEAD" --docs "$DOCS" --registration "$REG" \
    > "$LOGS/r11_compute_stdout.log" 2>&1 || die "r11_compute failed ($LOGS/r11_compute_stdout.log)"
  for d in deter deter_r10style; do
    cp "$RAW/$d/summary.json" "$SUM/r11_${d}_summary.json"
    cp "$RAW/$d/exact_expectation.json" "$SUM/r11_${d}_exact.json"
    for v in r10 r10_a05 r10_a09; do cp "$RAW/$d/addresses_$v.csv" "$SUM/r11_${d}_addresses_$v.csv"; done
  done
  cp "$LOGS/r11_compute_stdout.log" "$SUM/"
  ( cd "$SUM" && sha256sum -- * | grep -v ' SHA256SUMS.txt$' > SHA256SUMS.txt )
  done_mark aggregate
  st "done"
  say "all finished. aggregation: $SUM"
}

case "${1:-}" in
  gate) gate0 ;;
  prepare) prepare ;;
  run) run_all ;;
  *) echo "usage: $0 gate | prepare | run | status"; exit 2 ;;
esac
