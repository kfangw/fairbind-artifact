# C35: share of sales worth at least the buyer's duty cost

Post hoc calculation; it has no registered decision rule. The rules, fixed before the run, are in `calc-rules.md`.
`c35_duty_share.py` takes the duty cost c_D to be the gas of one dispute (as the original calculation in
`P1_posthoc`) and gives the share of sales with value >= c_D, by count and by value, for every sale of the R12 seller
set S1r in the busy and median windows and for the six data sellers in all three windows.

```sh
cd measurement/docs/11_journal/C35_duty-cost-share
python3 -I c35_duty_share.py --lists $RAW/lists --out /tmp/c35d      # about 25 s
```

`$RAW/lists` holds the registered R12 sale lists (about 4.8 GB, written by `run_r12.sh` from the raw data of the
top-level README, section 4; not included). The other inputs are in this bundle: `R12/results/r12_addr_<window>.csv`,
`F/data-review/target_sellers_values.csv`, `G10_gas/logs_b/g10b_l1fee.tsv.gz`, `G11_gas/logs/p5_l1fee.tsv.gz`.

## Cells

| Cell | c_D (USD) | Meaning |
| --- | --- | --- |
| D2, 0.010 gwei (main) | 0.008584 | original calculation's main value, cost-model gas price |
| D1, 0.010 gwei | 0.004012 | opening only (lower end) |
| D2, 0.0161 gwei | 0.013778 | largest base fee in the sample |
| D2, 1 gwei | 0.851522 | floor of the duty fee cap, the client's reserve unit |

## Checks

All pass (`checks` of `results/c35_results.json`): the D2 values at 1 and 0.0161 gwei; the eight rows of the
`P1_posthoc` table (sale counts and shares of c_D > v), e.g. median 1,153,924 sales, 83.69%, 2.05% and busy 762,322
sales, 80.17%, 5.79%; each of the six full addresses against the s1b bins of `target_sellers_values.csv`; the six
tier-0/1 revenues 1,536.7264, 1,218.43 and 778.0894 USDC against the article's 1,536.73, 1,218.43 and 778.09.

## Results

All replayed sales (S1r), share with value >= c_D:

| Window | Sellers | Sales | Cell | Count share | Value share | Per-seller count share Q1 / median / Q3 | Per-seller value share median | Sellers with all / no sales >= c_D |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| busy | 178 | 762,322 | D2 0.010 (main) | 19.83% | 94.21% | 8.07 / 75.96 / 100.00% | 98.29% | 71 / 27 |
| busy | | | D1 0.010 | 25.00% | 95.11% | 17.59 / 99.43 / 100.00% | 100.00% | 88 / 14 |
| busy | | | D2 0.0161 | 10.87% | 91.35% | 0.00 / 14.24 / 80.41% | 76.94% | 34 / 55 |
| busy | | | D2 1 | 1.52% | 68.96% | 0.00 / 0.00 / 0.27% | 0.00% | 2 / 126 |
| median | 289 | 1,153,924 | D2 0.010 (main) | 16.31% | 97.95% | 4.62 / 45.45 / 100.00% | 94.22% | 89 / 52 |
| median | | | D1 0.010 | 22.48% | 98.33% | 23.61 / 88.89 / 100.00% | 99.68% | 127 / 35 |
| median | | | D2 0.0161 | 9.49% | 97.21% | 0.00 / 13.70 / 56.38% | 68.01% | 36 / 84 |
| median | | | D2 1 | 2.60% | 89.65% | 0.00 / 0.00 / 0.00% | 0.00% | 4 / 237 |
| quiet | no replay | | | | | | | |

Six data sellers, tier-0/1 parts, main cell (D2, 0.010 gwei). Busy and median windows are exact; the quiet window
has value bins only, so a bin containing c_D gives a range, with the reference imputation in parentheses:

| Seller | Busy count | Busy value | Median count | Median value | Quiet count | Quiet value |
| --- | --- | --- | --- | --- | --- | --- |
| StableEnrich (<= 0.5 USDC) | 98.81% | 99.94% | 95.42% | 99.75% | 33.17-97.60% (95.30) | 78.69-99.91% (99.68) |
| OneSource | 3.79% | 8.83% | 13.92% | 39.25% | 11.36-48.06% (26.44) | 39.18-91.39% (59.63) |
| CoinMarketCap | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| StableApify | 98.45% | 99.50% | 98.15% | 99.20% | 46.15-100.00% (98.29) | 49.93-100.00% (99.14) |
| Exa (<= 0.001 USDC) | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| CoinStats (<= 0.01 USDC) | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| Six together | 84.80% | 98.09% | 60.76% | 95.69% | 28.21-85.80% (79.11) | 76.14-99.33% (97.07) |

The six together have 50,398 (busy), 54,658 (median) and 36,505 (quiet) sales. Other cells, six together (count /
value share):

| Cell | Busy | Median | Quiet |
| --- | --- | --- | --- |
| D1 0.010 | 91.20% / 99.30% | 68.54% / 97.80% | 66.65-96.83% / 94.17-99.85% (86.54 / 98.76) |
| D2 0.0161 | 46.54% / 84.53% | 19.04% / 76.34% | 8.16-27.91% / 63.23-76.00% (no imputation for OneSource's bin) |
| D2 1 | 0.00% / 0.00% | 0.00% / 0.00% | 0.00% / 0.00% (exact) |

At 1 gwei no tier-0/1 sale of the six sellers reaches c_D, since all are at most 0.5 USDC. For the full addresses
(`six_full`) the main cell gives 81.17% / 97.13% (busy) and 58.05% / 94.40% (median).

## Limits

The duty cost is one dispute's gas, as in the original calculation; the substitution proof, repeated disputes, the
reserve's capital cost and timeouts are left out. The quiet window has no per-sale data, so it has no all-sales cell
and the six sellers are exact only up to the bin ranges; the main c_D lies inside the (0.001, 0.01] bin, so the range
is wide. The busy and median sales are CDP settlements only, and S1r is the R12 seller set drawn from the 415 replayed
addresses.

## Outputs

`results/c35_results.json` (costs, thresholds, checks, every cell), `results/c35_sellers_<window>.csv` (per S1r
seller: sales, revenue, count and value at or above c_D per cell). A rerun reproduces the CSV files byte for byte; the
JSON differs only in `script_sha256`.
