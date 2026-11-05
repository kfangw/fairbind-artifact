#!/usr/bin/env bash
# Runs every P5 measurement, the L1 data fee and the summary.
#   L1PARAMS  l1fee.py output whose first line holds the fork block's L1 inputs
set -euo pipefail
L1PARAMS="${L1PARAMS:?l1fee.py output with the fork-block header line}"
cd "$(git rev-parse --show-toplevel)"
R=contracts/test/g10/p5/run_p5.sh
$R selfsub test_gas_selfSubmission
$R bundle test_gas_bundleAnchor
$R vrf test_gas_sharedVrf
$R vrfdirect test_gas_directSample
$R release test_gas_release
$R t1a test_gas_proveTier1a
$R t0 test_gas_proveTier0
$R disputes test_gas_disputes
python3 -I contracts/test/g10/g10c/l1big.py --params "$L1PARAMS" --out p5-out/p5_l1fee.tsv \
  p5-out/{selfsub,bundle,vrf,vrfdirect,release,t1a,t0,disputes}.tsv
python3 -I contracts/test/g10/p5/summarize_p5.py p5-out/p5_l1fee.tsv > p5-out/p5_summary.tsv
