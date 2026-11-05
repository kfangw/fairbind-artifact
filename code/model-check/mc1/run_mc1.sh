#!/bin/sh
# Run every MC1 grid on this revision and write results/<grid>.json.
set -e
cd "$(dirname "$0")"
python3 -m unittest test_model
W=${W:-2}
for g in SELF BP1 SP1 E5_pre_anchor E5_client E5_rdl E5_dkey G2; do
  python3 run.py "$g" "$W" | tee "results_$g.log"
done
python3 report.py results/*.json
