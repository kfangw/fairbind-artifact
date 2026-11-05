# C35 duty-cost share: calculation rules

Fixed before the calculation was run; later changes would be listed as deviations in `README.md`.
**Post hoc calculation; it has no registered decision rule.**

The article says only that the duties of the buyer's signing client cost more gas than most replayed sales by count.
This calculation gives, per window, the share of sales for which protection pays, that is, sales whose value is at
least the duty cost, by count and by value.

## 0. Known when the rules were written

* The article's discussion of buyer duties, its evaluation setting, cost table and claims table, security goal G6
  and the proofs appendix.
* The source of the article's claim: `P1_posthoc` (its rule section 1, `p1_compute.py`, and the result table: count
  share of sales below the dispute cost 83.69% and 80.17%, value share 2.05% and 5.79%), and the buyer reserve unit
  of 0.851522 USD of the R12 cost setting.
* The form of the inputs: the two R12 sale lists (every CDP settlement, one row per sale),
  `F/data-review/target_sellers_values.csv` (per-seller value bins of the quiet window, source s1c), and the six data
  sellers' addresses and tier-0/1 parts in `K11/k11b.py`.

Not seen: the shares of the six sellers in the busy and median windows, every quiet-window value, and the six
sellers' values at prices other than 0.010 gwei.

## 1. Duty cost (as in the original calculation)

The original calculation (`P1_posthoc`, section 1) takes the duty cost to be **the gas of one dispute, c_D**, a
constant independent of the sale value.

* Main definition D2: open a non-delivery dispute with 1 KB (166,809 gas) plus a decryption challenge with 4 KB,
  mismatch and refund (187,750 gas); the L1 fee is the sum of `l1_fee_node_wei` of the rows
  `G10-6 open dispute 1 KB` and `G10-6 decryption check, misbehaviour proven 4 KB` of
  `G10_gas/logs_b/g10b_l1fee.tsv.gz`. Gas is read by row label from `G11_gas/logs/p5_l1fee.tsv.gz`.
* Lower end D1: opening only (166,809 gas plus its L1 fee).
* USD = gas x p x 1e-9 x 2,401.44 + L1 wei x 1e-18 x 2,401.44.
* Price p: main value 0.010 gwei (0.005 gwei x 2.0 of the cost model of appendix B, as the P1 main value);
  sensitivities 0.0161 gwei (largest base fee in the sample) and 1 gwei (floor of the duty fee cap, buyer reserve
  unit 0.851522 USD).
* Check: D2 is 0.851522 USD at 1 gwei and 0.013778 USD at 0.0161 gwei (six decimals).

Binding and receipt signatures are off-chain and cost no gas; the substitution proof's gas was not in the original
calculation and is not added (listed as a limit).

**Sales for which protection pays**: sales with value v_j >= c_D, the complement of the original calculation's
"dispute costs more than the sale" (c_D > v_j).

## 2. Shares

* Count share: #{j : v_j >= c_D} / #sales.
* Value share: sum_{v_j >= c_D} v_j / sum v_j.
* Per-seller count and value shares (median, Q1, Q3 with `numpy.quantile`, linear) for the full sale set only.
* Comparisons in integer atomic units (c_D rational); percentages rounded to two decimals only in tables.

## 3. Sale sets and windows

### 3.1 All sales (the population of the original calculation)

* Busy window (2026-06-09 to 06-29) and median window (2026-07-24 to 08-13): R12 sale lists, every sale received by
  seller set S1r (289 and 178 sellers, `in_S1r` of `R12/results/r12_addr_<window>.csv`) over the whole window
  [F, Z]. The list SHA-256 must equal the R12 registration (091476..., 91412e...).
* Quiet window: there is no R12 replay and no per-sale list, so the all-sales cell is reported as "no replay".

### 3.2 The six data sellers (the article's evaluation setting)

Sellers and addresses are `ADDR` of `K11/k11b.py`. The main definition is the tier-0/1 part used by the cost results
(K11b set T01t): StableEnrich sales up to 0.5 USDC, Exa up to 0.001 USDC, CoinStats up to 0.01 USDC, and every sale of
OneSource, CoinMarketCap and StableApify. As a secondary view, each full address (no part cut). Per seller and the
six together.

* Busy and median windows: counted exactly per sale from the R12 lists (CDP settlements, the source of the cost
  results). Checks: per-seller count and value equal the sum of the s1b bins of the same window in
  `target_sellers_values.csv`, and the six T01t revenues sum to the article's 1,536.73 and 1,218.43 USDC (two
  decimals).
* Quiet window: only the s1c value bins of `target_sellers_values.csv` (upper ends 0.001, 0.01, 0.1, 0.2, 0.5, 1, 5,
  inf, upper end inclusive). Check: the six T01t revenues sum to 778.09 USDC.
  * A bin entirely above or below c_D is counted exactly.
  * For the bin containing c_D (lower end lo < c_D <= upper end up), with count n and sum S, the number m of sales
    >= c_D is bounded by max(0, ceil((S - n c_D) / (up - c_D))) and min(n, floor((S - n lo) / (c_D - lo))), given that
    every value lies in (lo, up] and the values sum to S. The value share range comes from the same extreme
    arrangements (lower end: m_min sales at up and the rest below c_D; upper end: m_max sales at or above c_D and the
    rest just above lo, without exceeding S).
  * Reference imputation: the share of sales >= c_D by count and by value within the same bin, in the same seller's
    pooled busy and median per-sale data, is carried over to the bin and clipped to the range. The range is the
    main report; the imputation is for reference.

## 4. Reproduction checks (before reporting)

1. The USD values of D2 equal those of section 1.
2. On all S1r sales at D2 and 0.010 gwei, the count and value shares of c_D > v_j and the sale counts equal the P1
   table: median window 1,153,924 sales, 83.69%, 2.05%; busy window 762,322 sales, 80.17%, 5.79%. The D1, 0.0161 and
   1 gwei rows also equal the P1 table.
3. The per-seller count and revenue checks of section 3.2.

If 1 or 2 fails, no share is reported and the cause is recorded. If 3 fails, the six sellers' values of that window
are not reported.

## 5. If the result is unfavourable

Small shares are reported as they are. Statements use the main definition (D2, 0.010 gwei); the definitions and the
price grid are not changed after the results are seen.

## 6. Outputs

`c35_duty_share.py`, `results/c35_results.json`, `results/c35_sellers_<window>.csv` (per S1r seller). No copy of the
sale lists.
