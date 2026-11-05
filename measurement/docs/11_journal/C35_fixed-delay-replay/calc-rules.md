# C35 fixed-delay replay: calculation rules

Fixed before the calculation was run; later changes would be listed as deviations in `README.md` (there are none).
**Post hoc calculation; it has no registered decision rule.**

The article's separation section names a "fourth rule": keep the freeze of rule R5 and the deduction, and pay each
sale a fixed delay D >= Delta_f after its settlement. The rule avoids a rate-sized bond but adds one assumption, that
failure declarations are included in time. This calculation gives its locked money and holding time on the same R12
replay as FairBind, the two bonds and the rolling reserve (`C34_ASP-replay`).

## 0. Known when the rules were written

* The article's release lag (300k + 1,951 blocks; Delta_f = 2,251 at k = 1 and 11,551 at k = 32) and its replay table
  of locked money: FairBind 724.70 and 324.49 USDC; oracle mean-rate bond 976.56, 557.85, 489.01, 238.80; ratios
  0.74, 1.30, 0.66, 1.36; at k = 1 0.97 and 0.98; rolling-reserve escrow 40,328.04 and 7,937.48.
* `C34_ASP-replay/c34_asp.py`, `C32/W3_replay/w3_compare.py` and their arguments.
* The R12 code `code/replay/experiments/replay/r12_compute.py` (`interval_numerators`, `fairbind_cells`,
  `window_results`, its `lag_cells` with L_FB = n x b + held(k*), `REGISTERED`), the keys of the R12 `sales.npz`, and
  the range of release - block in the k = 1 run (1,921 to 2,251).

Not seen: every value of section 2 below for the fourth rule, the worst-moment values, FairBind's worst-moment
locked money, and every amount-weighted mean hold.

## 1. Fraud payout equals FairBind's (not computed)

The fourth rule keeps R5's freeze (from a failed sale's settlement block, every later-settled unpaid sale is frozen)
and the deduction b = V. Suppose failure declarations are included in time. A sampled false sale c is declared
failed at the latest at its settlement block s_c plus the longest deadline Delta_f. A sale j settled after c is paid
at s_j + D >= s_c + Delta_f, so it is frozen before payment. Sales settled before c are not frozen under either rule.
On every sample, the false revenue paid to the seller is therefore the same under both rules, and so is its
expectation. The realized FairBind payout G of `C32/W3_replay` (false revenue settled before the first sampled false
sale) does not use the payment time, so it holds for the fourth rule too, and the FairBind rows of the payout tables
are also the fourth rule's rows.

The equality needs timely inclusion. If a declaration is included later than D minus the time left to its deadline,
sales whose payment time falls in between escape the freeze. The replay does not model such delays and does not
compute that loss.

## 2. Definitions

### 2.1 Shared assumptions (as R12, W3, C34)

* Replay: sales of the R12 cost-setting replay (`$RAW/{median,busy}_r12cost/k<k>/condition-01-seed-0/sales.npz`),
  seller set S1r (289 sellers in the median window, 178 in the busy window; `in_S1r` of
  `R12/results/r12_addr_<window>.csv`). V = b = 1 USDC.
* Time set: R12's T = [F + 31,073, Z], |T| = n_avg (R12 `Window`); two-second blocks.
* Per seller, k* is `k_star`, the own lag `L_own` = 300k* + 1,951, and Delta_f is `L_k1` = 2,251, all from
  `r12_addr_<window>.csv`.

### 2.2 Locked money of the fourth rule

Sale j (seller i, settlement block b_j, value v_j) is held during [b_j, b_j + D). Seller i's held balance is
held^D_i(t) = sum_j v_j [b_j <= t < b_j + D], the R12 `interval_numerators` with release = b + D; FairBind's held
balance is the same function with the run's release.

* Column Delta_f: D = 2,251 blocks for every seller, the least the rule allows. The replay has one profile, so the
  longest deadline across profiles equals Delta_f.
* Column own: D_i = L_own,i = 300k*_i + 1,951 per seller, FairBind's longest hold for that seller.
* Deduction: the rule keeps R5 and the deduction, so b is locked per seller; locked money = n x b + held sales, the
  definition of FairBind's locked money in the replay table.
* Time average: n x b + (1/n_avg) sum_{t in T} sum_i held^D_i(t).
* Worst moment, two forms: (a) sum of per-seller maxima n x b + sum_i max_{t in T} held^D_i(t), as for the bonds;
  (b) simultaneous maximum n x b + max_{t in T} sum_i held^D_i(t). The replay table has no worst-moment value for
  FairBind, so FairBind's is computed with both forms from the same `sales.npz` (at k*, and for reference with every
  seller at k = 1).
* FairBind's time average is R12's `L_FB` (k*: 724.70, 324.49); for reference also every seller at k = 1 (R12 k
  curve `L_FB`).
* Ratios: fourth rule / FairBind (k*), below 1 if the fourth rule locks less; also against FairBind at k = 1.
* Per seller: the number of sellers whose b + held^D_i (time average) is below and above b + H_i(k*).
* Ratios to the oracle mean-rate bond (R12 `sumC_M`) and the history bond (`sumB_H`), in the direction of the table.

### 2.3 Holding time

* Longest hold: FairBind 300k* + 1,951 blocks per seller (range over S1r and the k* distribution); the fourth rule D.
* Amount-weighted mean hold: sum_j v_j (release_j - b_j) / sum_j v_j over every S1r sale of the window, not truncated
  at the window end. FairBind uses the release of the k* run (and of the k = 1 run), the fourth rule D.

### 2.4 Reproduction checks (before reporting)

* The per-seller Hnum_k (k = 1 and k*) recomputed from `sales.npz` equal `r12_addr_<window>.csv` as integers, and
  their sums equal R12's S1r `L_FB` (724.70, 324.49) and the k = 1 `L_FB` of the k curve.
* The SHA-256 of each `sales.npz` equals `R12/results/r12_sales_sha256.txt`.
* held^D computed from the R12 sale lists (`read_list`, window list) as cumulative revenue Rev(t - D, t] equals the
  value from `sales.npz` for every seller.
* `w3_compare.py` and `c34_asp.py`, unchanged, rerun to equal their recorded outputs apart from the environment keys,
  so the payout, bond and reserve values and the inputs of this calculation come from the same replay.

If any check fails, the fourth rule's values are not reported and the cause is recorded.

## 3. If the result is unfavourable

If the fourth rule locks less or holds sales for less time than FairBind (expected in column Delta_f), the values
are reported as they are. What FairBind gains in return is that the freeze precedes payment without the timely
inclusion assumption (Lemma A(b)), a difference of assumptions rather than of numbers. Definitions, columns and the
time set are not changed after the results are seen.

## 4. Outputs

`c35_fixed.py`; `results/c35_fixed.json`; per-seller `results/c35_sellers_<window>.csv`. No copy of `sales.npz` or of
the sale lists.
