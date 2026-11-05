# C35: locked money of a fixed payment delay on the bond replay

Post hoc calculation; it has no registered decision rule. The rules, fixed before the run, are in `calc-rules.md`.
`c35_fixed.py` replays the "fourth rule" of the article's separation section (keep R5's freeze and the deduction,
pay each sale a fixed delay D after its settlement) on the sales of the R12 cost replay and sets its locked money and
holding time against FairBind's release cursor. D is either Delta_f = 2,251 blocks for every seller or each seller's
own lag 300k* + 1,951. Fraud payout is not computed: with timely inclusion of failure declarations it equals
FairBind's on every sample (`calc-rules.md`, section 1).

```sh
cd measurement/docs/11_journal/C35_fixed-delay-replay
python3 -I c35_fixed.py --raw $RAW --replayer ../../../../code/replay --out /tmp/c35f     # about 30 s
```

`$RAW` holds the R12 replay outputs (`<window>_r12cost/k<k>/condition-01-seed-0/sales.npz` and
`sales_addresses.json`) and the registered sale lists (`$RAW/lists`), written by `run_r12.sh` from the raw data of
the top-level README, section 4 (not included). The script also reads `R12/results/` of this bundle.

## Checks

All pass (`pass` true, empty `problems` in both windows of `results/c35_fixed.json`): the `sales.npz` hashes equal
`R12/results/r12_sales_sha256.txt` and the list hashes the R12 registration; per-seller Hnum at k* and k = 1
recomputed from `sales.npz` equal `R12/results/r12_addr_<window>.csv`; the summed FairBind locked money equals R12's
`L_FB` (k*: 724.70 and 324.49; k = 1: 540.23 and 233.99); the k = 1 and k* runs and the window list hold the same
sales; the fixed-delay held balance computed from the window list as Rev(t - D, t] equals the one from `sales.npz`
over all of T; L_own = 300k* + 1,951 and L_k1 = 2,251.

## Results

USDC, sum over the S1r sellers (289 median, 178 busy), V = b = 1. Locked money is n x b + held sales.

| Row | Median own | Median Delta_f | Busy own | Busy Delta_f |
| --- | --- | --- | --- | --- |
| Fourth rule's D | own lag | 2,251 | own lag | 2,251 |
| Fourth rule, time average | 978.40 | 557.76 | 483.50 | 238.03 |
| FairBind (k*), time average | 724.70 | 724.70 | 324.49 | 324.49 |
| FairBind (every seller k = 1), time average | 540.23 | 540.23 | 233.99 | 233.99 |
| FairBind (k*) / fourth rule | 0.74 | 1.30 | 0.67 | 1.36 |
| FairBind (k = 1) / fourth rule | 0.55 | 0.97 | 0.48 | 0.98 |
| Fourth rule / oracle mean-rate bond | 1.00 | 1.00 | 0.99 | 1.00 |
| Fourth rule / history bond | 0.41 | 0.67 | 0.29 | 0.73 |
| Sellers: fourth rule locks less, more, equal | 0, 289, 0 | 226, 63, 0 | 0, 176, 2 | 153, 23, 2 |
| Fourth rule, worst moment (sum of per-seller maxima) | 4,226.07 | 3,094.01 | 3,776.04 | 3,147.46 |
| FairBind (k*), same | 3,926.25 | 3,926.25 | 3,591.48 | 3,591.48 |
| FairBind (k = 1), same | 2,878.38 | 2,878.38 | 3,129.88 | 3,129.88 |
| Fourth rule, worst moment (simultaneous maximum) | 1,872.95 | 1,128.59 | 1,740.29 | 1,352.12 |
| FairBind (k*), same | 1,597.71 | 1,597.71 | 1,273.06 | 1,273.06 |
| FairBind (k = 1), same | 1,126.52 | 1,126.52 | 1,228.90 | 1,228.90 |

The two "equal" sellers of the busy window have no revenue in it. Holding time in blocks:

| Row | Median | Busy |
| --- | --- | --- |
| FairBind (k*) longest hold | 2,251 to 11,551 (k* = 32: 219 sellers) | 2,251 to 11,551 (k* = 32: 150 sellers) |
| Fourth rule Delta_f longest hold | 2,251 | 2,251 |
| Amount-weighted mean hold, FairBind (k*) | 3,646.4 | 5,410.9 |
| Amount-weighted mean hold, FairBind (k = 1) | 2,104.4 | 2,100.4 |
| Amount-weighted mean hold, fourth rule Delta_f | 2,251.0 | 2,251.0 |
| Amount-weighted mean hold, fourth rule own | 5,756.6 | 11,514.8 |

At D = Delta_f the fourth rule locks 23% and 27% less than FairBind at k*; at the same longest hold FairBind locks
less (k = 1 against Delta_f, and k* against the own lag), because the cursor pays at the end of an epoch, before the
longest hold has elapsed. The comparison leaves out the fourth rule's payout transactions (one payment time per
sale), which FairBind's k* is chosen to reduce, and the loss when a failure declaration is included late.

## Outputs

`results/c35_fixed.json` (window sums, comparisons, input hashes), `results/c35_sellers_<window>.csv` (per seller:
k*, own lag, revenue, time-average and maximum held balance under each rule). A rerun reproduces the CSV files byte
for byte; the JSON differs only in the recorded SHA-256 of `r12_compute.py` (translated in this bundle) and, with
another Python or numpy, in the environment block.
