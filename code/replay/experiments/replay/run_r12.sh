#!/bin/bash
# R12: FairBind in the cost setting against deployable bonds (registration R12_preregistration.md in the research repository).
#   bash experiments/replay/run_r12.sh gate       # G0 only: sealed registration hash, its commit on origin/main
#   bash experiments/replay/run_r12.sh prepare    # code, environment, tests, input hashes, lists, synthetic selfcheck
#   nohup bash experiments/replay/run_r12.sh run > /dev/null 2>&1 &    # G0, prepare, bridge, cost k sweep, aggregation
#   bash experiments/replay/run_r12.sh status
# The replay flags come from the registered block of the sealed registration (r12_compute.py print-flags), so the
# replay, the gates of the aggregation and the registration share one source. Every step leaves $SCRATCH/done/<step>;
# a repeated call skips finished steps and k values. Raw outputs (sales.npz stays out of git) go to $SCRATCH/raw, the
# aggregation to $SCRATCH/summary. Copying the aggregation into docs/11_journal/R12/results/ and committing is done by hand.
set -euo pipefail
RESEARCH="${RESEARCH:-./research-clone}"
SCRATCH="${SCRATCH:-./scratch}"
RAWDATA="${RAWDATA:-./raw-data}"
PARALLEL="${PARALLEL:-2}"           # windows replayed at the same time (a busy-window run needs about 5 GB)
DOCS="$RESEARCH/docs"
REG="$DOCS/11_journal/R12/R12_preregistration.md"
REG_REL="docs/11_journal/R12/R12_preregistration.md"
RAW="$SCRATCH/raw"; SUM="$SCRATCH/summary"; LOGS="$SCRATCH/logs"; DONE="$SCRATCH/done"
REPO="$SCRATCH/replayer"; VENV="$SCRATCH/.venv"; LISTS="$RAW/lists"
CODE_URL="${CODE_URL:-https://example.org/fairbind-code.git}"
CODE_BRANCH="${CODE_BRANCH:-r12-replay}"
EXPECT_HEAD="${EXPECT_HEAD:-SET-AT-SEAL}"   # registration 2.4: the replayer commit; must appear in the sealed file

# Pinned environment (registration 9, P6): the numpy and scipy of the R11 run; S0 checks them against the block.
NUMPY_PIN=2.5.4
SCIPY_PIN=1.18.1
# Every input path and hash comes from the registered block (r12_compute.py print-window, check-inputs).

mkdir -p "$RAW" "$SUM" "$LOGS" "$DONE" "$LISTS"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
say() { echo "[$(date -u '+%F %T')Z] $*" | tee -a "$LOGS/run.log"; }
die() { say "stopped: $*"; st "stopped: $*"; exit 1; }
st() { printf '{"phase": "%s", "time_utc": "%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$SCRATCH/status.json"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
check_sha() { [ -e "$1" ] || die "missing: $1"; local g; g="$(sha "$1")"; [ "$g" = "$2" ] || die "hash differs: $1 ($g, expected $2)"; }
done_mark() { date -u +%FT%TZ > "$DONE/$1"; }
is_done() { [ -f "$DONE/$1" ]; }
PY() { "$VENV/bin/python" -I "$@"; }

if [ "${1:-}" = "status" ]; then
  cat "$SCRATCH/status.json" 2>/dev/null || echo "not started"
  ls "$DONE" 2>/dev/null | tr '\n' ' '; echo
  tail -n 8 "$LOGS/run.log" 2>/dev/null || true
  exit 0
fi

# ---------------------------------------------------------------- G0: the sealed registration is on origin/main
gate0() {
  [ -f "$REG" ] || die "G0: registration $REG missing (seal first: registration section 10)"
  local SHAFILE="${REG%.md}.sha256"
  [ -f "$SHAFILE" ] || die "G0: R12_preregistration.sha256 missing"
  local WANT; WANT="$(awk '{print $1; exit}' "$SHAFILE")"
  [ "${#WANT}" -eq 64 ] || die "G0: $SHAFILE has no SHA-256 in its first word"
  check_sha "$REG" "$WANT"
  local REMOTE_HEAD
  REMOTE_HEAD="$(git -C "$RESEARCH" ls-remote origin refs/heads/main | cut -f1)"
  [ "${#REMOTE_HEAD}" -eq 40 ] || [ "${#REMOTE_HEAD}" -eq 64 ] || die "G0: git ls-remote origin main gave nothing"
  git -C "$RESEARCH" fetch -q origin "$REMOTE_HEAD" || git -C "$RESEARCH" fetch -q origin main || die "G0: fetch failed"
  local REMOTE_REG REMOTE_STATED
  REMOTE_REG="$(git -C "$RESEARCH" cat-file blob "$REMOTE_HEAD:$REG_REL" | sha256sum | cut -d' ' -f1)" \
    || die "G0: $REG_REL is not in origin/main ($REMOTE_HEAD)"
  [ "$REMOTE_REG" = "$WANT" ] || die "G0: origin/main carries a registration with hash $REMOTE_REG, not the sealed $WANT"
  REMOTE_STATED="$(git -C "$RESEARCH" cat-file blob "$REMOTE_HEAD:${REG_REL%.md}.sha256" | awk '{print $1; exit}')" \
    || die "G0: the .sha256 file is not in origin/main"
  [ "$REMOTE_STATED" = "$WANT" ] || die "G0: origin/main's .sha256 says $REMOTE_STATED, not $WANT"
  [ "$EXPECT_HEAD" != "SET-AT-SEAL" ] && [ "${#EXPECT_HEAD}" -eq 40 ] || die "G0: EXPECT_HEAD (replayer commit) is not set"
  grep -q "$EXPECT_HEAD" "$REG" || die "G0: the sealed registration does not name the replayer commit $EXPECT_HEAD"
  printf '{"registration_sha256": "%s", "origin_main": "%s", "replayer_commit": "%s", "checked_utc": "%s"}\n' \
    "$WANT" "$REMOTE_HEAD" "$EXPECT_HEAD" "$(date -u +%FT%TZ)" > "$SUM/g0.json"
  say "G0: registration $WANT is on origin/main $REMOTE_HEAD; replayer $EXPECT_HEAD"
}

# ---------------------------------------------------------------- prepare: no window replay
prepare() {
  st "prepare"
  [ "$EXPECT_HEAD" != "SET-AT-SEAL" ] || die "EXPECT_HEAD is not set"
  if [ ! -d "$REPO/.git" ]; then git clone -q "$CODE_URL" "$REPO"; fi
  git -C "$REPO" fetch -q origin "$CODE_BRANCH" || die "cannot fetch the code branch $CODE_BRANCH"
  git -C "$REPO" checkout -q --detach "$EXPECT_HEAD" || die "commit $EXPECT_HEAD is missing"
  [ -z "$(git -C "$REPO" status --porcelain)" ] || die "the replayer tree is not clean"
  say "replayer $EXPECT_HEAD, clean tree"
  if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV" && "$VENV/bin/pip" install -q --upgrade pip && "$VENV/bin/pip" install -q "numpy==$NUMPY_PIN" "scipy==$SCIPY_PIN" \
      || die "cannot build the Python environment"
  fi
  "$VENV/bin/python" -c "import numpy, scipy, sys; print('python', sys.version.split()[0], 'numpy', numpy.__version__, 'scipy', scipy.__version__)" | tee -a "$LOGS/run.log"
  # S0: the registered block of the sealed file equals the code (no replay before this holds)
  (cd "$REPO/experiments/replay" && PY r12_compute.py check-registration --registration "$REG" \
    --numpy "$NUMPY_PIN" --scipy "$SCIPY_PIN") >> "$LOGS/run.log" 2>&1 \
    || die "S0: the registered block differs from r12_compute.py or the environment pin ($LOGS/run.log)"
  if ! is_done tests; then
    (cd "$REPO/experiments/replay" && for t in test_r12_compute test_r11 test_r11_compute test_release10 \
       test_release10_bruteforce test_release8; do "$VENV/bin/python" -m unittest "$t" || exit 1; done) \
       > "$LOGS/tests.log" 2>&1 || die "replayer tests failed ($LOGS/tests.log)"
    done_mark tests; say "tests passed ($(grep -cE '^OK' "$LOGS/tests.log") suites)"
  fi
  # S1: synthetic end-to-end with the registered flags (registration 9, gate S1)
  if ! is_done selfcheck; then
    (cd "$REPO/experiments/replay" && PY r12_compute.py selfcheck --registration "$REG" --work "$SCRATCH/selfcheck") \
      > "$LOGS/selfcheck.log" 2>&1 || die "S1: synthetic selfcheck failed ($LOGS/selfcheck.log)"
    cp "$SCRATCH/selfcheck/selfcheck.json" "$SUM/selfcheck.json"
    done_mark selfcheck; say "S1: synthetic selfcheck passed"
  fi
  (cd "$REPO/experiments/replay" && PY r12_compute.py check-inputs --registration "$REG" --rawdata "$RAWDATA" \
    --docs "$DOCS") >> "$LOGS/run.log" 2>&1 || die "G1: input hashes differ ($LOGS/run.log)"
  for W in median busy; do
    IFS=$'\t' read -r DIR PDIR F WANT P PWANT _ _ _ < <(winfo "$W")
    if [ ! -f "$LISTS/$F" ] || [ ! -f "$LISTS/$P" ] || [ "$(sha "$LISTS/$F")" != "$WANT" ] \
       || [ "$(sha "$LISTS/$P")" != "$PWANT" ]; then
      say "building the lists ($W, with the prior 14 days)"
      (cd "$REPO/experiments/replay" && PY chain_inputs.py build --chain base --dir "$RAWDATA/$DIR" \
        --prior-dir "$RAWDATA/$PDIR" --out "$LISTS/$W") >> "$LOGS/lists.log" 2>&1 || die "chain_inputs build failed ($W)"
    fi
    check_sha "$LISTS/$F" "$WANT"
    check_sha "$LISTS/$P" "$PWANT"
  done
  done_mark prepare
  say "prepare finished: window and prior lists verified"
}

winfo() { (cd "$REPO/experiments/replay" && PY r12_compute.py print-window --registration "$REG" --window "$1"); }
list_of() { local x; x="$(winfo "$1" | cut -f3)"; echo "$LISTS/$x"; }
cond_of() { local x; x="$(winfo "$1" | cut -f7)"; echo "$DOCS/$x"; }
ref_dir() { local x; x="$(winfo median | cut -f8)"; echo "$DOCS/$x"; }
d2cfg() { local x; x="$(winfo median | cut -f9)"; echo "$DOCS/$x"; }

sweep() {   # kind window klist
  local KIND="$1" W="$2" KL="$3" key="${1}_${2}"
  is_done "$key" && return 0
  local FLAGS
  FLAGS="$(cd "$REPO/experiments/replay" && PY r12_compute.py print-flags --registration "$REG" --kind "$KIND")" \
    || { say "print-flags failed"; return 1; }
  say "replay $KIND $W (k = $KL; flags: $FLAGS)"
  # shellcheck disable=SC2086
  (cd "$REPO/experiments/replay" && "$VENV/bin/python" r11_k_sweep.py --k "$KL" --out "$RAW/${W}_r12${KIND}" -- \
    --settlements "$(list_of "$W")" --conditions-file "$(cond_of "$W")" --reference-dir "$(ref_dir)" \
    --d2-config "$(d2cfg)" $FLAGS) >> "$LOGS/${KIND}_${W}.log" 2>&1 || { say "replay $KIND $W failed"; return 1; }
  done_mark "$key"; say "replay $KIND $W finished"
}

run_all() {
  st "gate"
  gate0
  is_done prepare || prepare
  st "bridge (R11 main setting at V 1, k = 1)"
  sweep bridge median 1 & local p1=$!
  if [ "$PARALLEL" -ge 2 ]; then sweep bridge busy 1 & local p2=$!; wait $p1 || die "bridge median"; wait $p2 || die "bridge busy"
  else wait $p1 || die "bridge median"; sweep bridge busy 1 || die "bridge busy"; fi
  st "cost setting k sweep"
  local KL; KL="$(cd "$REPO/experiments/replay" && PY r12_compute.py print-ks --registration "$REG")"
  sweep cost median "$KL" & local p3=$!
  if [ "$PARALLEL" -ge 2 ]; then sweep cost busy "$KL" & local p4=$!; wait $p3 || die "cost median"; wait $p4 || die "cost busy"
  else wait $p3 || die "cost median"; sweep cost busy "$KL" || die "cost busy"; fi
  st "aggregate"
  (cd "$REPO/experiments/replay" && PY r12_compute.py compute --registration "$REG" --raw "$RAW" --lists "$LISTS" \
    --docs "$DOCS" --out "$SUM" --code-commit "$EXPECT_HEAD") > "$LOGS/r12_compute_stdout.log" 2>&1 \
    || die "r12_compute failed ($LOGS/r12_compute_stdout.log)"
  cp "$LOGS/r12_compute_stdout.log" "$SUM/"
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
