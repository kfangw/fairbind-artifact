# C32: replay comparison, deterrence margin, base-fee filling cost, out-of-window k

Post hoc calculations; none of them has a registered decision rule. Each script computes its input paths from its
own location, so run it from its directory. Comments, labels and table headings were translated as described in
`ANONYMIZATION.md` (section 2); the calculation documents they cite (`calc-rules.md`) are not included, and the
scripts record `absent` as their fingerprint.

| Folder | Script | What it computes | Inputs in this bundle |
| --- | --- | --- | --- |
| `W3_replay/` | `w3_compare.py` | FairBind's expected and realized fraud payout set against the bonds' uncovered revenue on the same replay, the same fraud strategy and the same start sets (worst moment and time average) | `R12/results/`, `R13/results/`, `R13/r13_sim.py`, `P2_posthoc/results/p2_c.json`; the R12 replay outputs `sales.npz` (not included) |
| `W3_replay/` | `w3_daily.py` | daily revenue per seller used by the bond replay against the raw daily settlement files | `R12/results/`, `code/replay`, `data/processed/agg_2026-10-21/days_*`; the R12 sale lists and the raw daily files (not included) |
| `W4_deterrence/` | `w4.py` | deterrence margin with the honest seller's per-sale cost share theta; cost of a deduction b = cV under the measured-gas model (V1u) and the earlier model (V0) | `P11_posthoc/p11.py` and the chain it imports, `P11_posthoc/results/p11.json`, `P8_posthoc/results/p8.json` |
| `W6_basefee/` | `w6.py` | cost of filling the shortest swap-proof window with Base's EIP-1559 base-fee response and a buyer fee ceiling; margins of the margin table | `P10_fit-conditions/results/p10.json`; Base parameters are constants in the script |
| `W7_out-of-window-k/` | `w7.py` | seller-epoch multiple k chosen in one window and applied in another; fit statements at thresholds of 5, 10 and 20% of revenue | `P9_posthoc`, `P10_fit-conditions`, `P11_posthoc`, `P6_posthoc`, `P10u_real-USDC/results/p10u.json` |

```sh
cd measurement/docs/11_journal/C32
(cd W4_deterrence && python3 -I w4.py --out /tmp/w4)          #  8 s
(cd W6_basefee && python3 -I w6.py > /tmp/w6_stdout.txt)        #  1 s; --check runs the checks only
(cd W7_out-of-window-k && python3 -I w7.py --out /tmp/w7)     # 11 s
(cd W3_replay && python3 -I w3_compare.py --raw $RAW --out /tmp/w3)
(cd W3_replay && python3 -I w3_daily.py --window median --replayer ../../../../../code/replay \
     --lists $RAW/lists --rawdata $RAWDATA --out /tmp/w3)     # and --window busy
```

`$RAW` is the directory of the R12 replay outputs (`<window>_r12cost/k1/condition-01-seed-0/sales.npz` and the sale
lists under `lists/`, written by `code/replay/experiments/replay/run_r12.sh`), and `$RAWDATA` the directory of the
raw daily files (README, section 4). Recorded outputs are in each `results/`. `W6_basefee/results/w6_stdout.txt` is
the standard output of the source script (the study kept this output only in a working document).
