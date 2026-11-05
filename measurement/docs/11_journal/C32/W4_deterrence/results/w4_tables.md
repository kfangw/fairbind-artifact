**all values post hoc calculations registered verdict none.** `w4.py` output. rule `calc-rules.md`.

check: k11b_reproduced True, v1u_vs_p11_ok True, manuscript_cost_ok True, v0_vs_p8_ok True, all_ok True; V1u vs p11.json max difference 0.0e+00, V0 vs p8.json max difference 0.0e+00.

## 1. deterrence: required c (conservative value, v/V → 0)

(a) honest service and comparison, (b) fraud not alternative among better side(θ > 1if not selling not) and comparison. margin target m ≥ xV.

| θ | (a) x 0 | (a) x 0.5 | (a) x 1 | (b) x 0 | (b) x 0.5 | (b) x 1 |
|---|---|---|---|---|---|---|
| 0 | 0.00 | 0.50 | 1.00 | 0.00 | 0.50 | 1.00 |
| 0.1 | 0.10 | 0.60 | 1.10 | 0.10 | 0.60 | 1.10 |
| 0.25 | 0.25 | 0.75 | 1.25 | 0.25 | 0.75 | 1.25 |
| 0.5 | 0.50 | 1.00 | 1.50 | 0.50 | 1.00 | 1.50 |
| 0.75 | 0.75 | 1.25 | 1.75 | 0.75 | 1.25 | 1.75 |
| 1 | 1.00 | 1.50 | 2.00 | 1.00 | 1.50 | 2.00 |
| 1.5 | 1.50 | 2.00 | 2.50 | 1.00 | 1.50 | 2.00 |
| 2 | 2.00 | 2.50 | 3.00 | 1.00 | 1.50 | 2.00 |

## 2. deterrence: deduction multiple c margin m/V (v → 0)

| θ | c 1 (a) | c 2 (a) | c 4 (a) | c 1 (b) | c 2 (b) | c 4 (b) |
|---|---|---|---|---|---|---|
| 0 | 1.00 | 2.00 | 4.00 | 1.00 | 2.00 | 4.00 |
| 0.1 | 0.90 | 1.90 | 3.90 | 0.90 | 1.90 | 3.90 |
| 0.25 | 0.75 | 1.75 | 3.75 | 0.75 | 1.75 | 3.75 |
| 0.5 | 0.50 | 1.50 | 3.50 | 0.50 | 1.50 | 3.50 |
| 0.75 | 0.25 | 1.25 | 3.25 | 0.25 | 1.25 | 3.25 |
| 1 | 0.00 | 1.00 | 3.00 | 0.00 | 1.00 | 3.00 |
| 1.5 | -0.50 | 0.50 | 2.50 | 0.00 | 1.00 | 3.00 |
| 2 | -1.00 | 0.00 | 2.00 | 0.00 | 1.00 | 3.00 |

Monte Carlo check(10^6 episodes, increase cheating seller):

| θ | c | v | V | simulated E[Δ] | standard error | closed form −m |
|---|---|---|---|---|---|---|
| 1 | 1 | 0.01 | 1 | -0.00985 | 0.00099 | -0.01000 |
| 0.5 | 1 | 0.01 | 1 | -0.50992 | 0.00050 | -0.51000 |
| 0 | 1 | 0.05 | 1 | -1.05000 | 0.00000 | -1.05000 |
| 1.5 | 2 | 0.1 | 1 | -0.59978 | 0.00142 | -0.60000 |
| 0.25 | 2 | 0.2 | 0.2 | -0.55000 | 0.00000 | -0.55000 |
| 1 | 1 | 1.5 | 1 | -1.00000 | 0.00000 | -1.00000 |

## 3. v/V correction and freeze revenue (V = 1, lower Grid)

| set | window | seller | R | sales n | mean v = v/V | failure one times freeze revenue R Δ_f / W_b (USDC = V multiple) |
|---|---|---|---|---|---|---|
| six seller sum | busy | StableEnrich(Out candidates excluded) | 1458.90 | 38369 | 0.03802 | 3.62 |
| six seller sum | busy | OneSource | 30.91 | 7194 | 0.004296 | 0.07669 |
| six seller sum | busy | CoinMarketCap | 43.62 | 4362 | 0.01 | 0.1082 |
| six seller sum | busy | StableApify | 3.00 | 193 | 0.01552 | 0.007431 |
| six seller sum | busy | Exa(0.001 or less) | 0.23 | 235 | 0.001 | 0.0005831 |
| six seller sum | busy | CoinStats(0.01 or less) | 0.07 | 45 | 0.001467 | 0.0001638 |
| six seller sum | median | StableEnrich(Out candidates excluded) | 1134.66 | 31237 | 0.03632 | 2.815 |
| six seller sum | median | OneSource | 81.22 | 22909 | 0.003545 | 0.2015 |
| six seller sum | median | CoinMarketCap | 1.63 | 163 | 0.01 | 0.004044 |
| six seller sum | median | StableApify | 0.62 | 54 | 0.01157 | 0.001551 |
| six seller sum | median | Exa(0.001 or less) | 0.27 | 267 | 0.001 | 0.0006625 |
| six seller sum | median | CoinStats(0.01 or less) | 0.03 | 28 | 0.001 | 6.948e-05 |
| six seller sum | quiet | StableEnrich(Out candidates excluded) | 726.43 | 27866 | 0.02607 | 2.523 |
| six seller sum | quiet | OneSource | 50.28 | 8329 | 0.006037 | 0.1747 |
| six seller sum | quiet | CoinMarketCap | 0.95 | 95 | 0.01 | 0.0033 |
| six seller sum | quiet | StableApify | 0.24 | 26 | 0.009231 | 0.0008337 |
| six seller sum | quiet | Exa(0.001 or less) | 0.18 | 178 | 0.001 | 0.0006183 |
| six seller sum | quiet | CoinStats(0.01 or less) | 0.01 | 11 | 0.001 | 3.821e-05 |
| BlockRun | busy | BlockRun | 105338.04 | 9656870 | 0.01091 | 261.4 |
| BlockRun | median | BlockRun | 127900.66 | 3319274 | 0.03853 | 317.4 |
| BlockRun | quiet | BlockRun | 2836.67 | 28710 | 0.0988 | 9.854 |

Figure 4 v̄ 0.001, 0.01, 0.1: required c by that much gives.

## 4. deduction cV cost: measured gas model V1u (Table cost)

| set | V | estimated | window | c 1 | c 1.1 | c 1.25 | c 1.5 | c 1.75 | c 2 | c 2.5 | c 3 | c 4 | c 2 − c 1 (%p) | c 4 − c 1 (%p) | k changed seller (c 2 / c 4) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| six seller sum | 1 | lower | busy | 9.21 | 9.23 | 9.26 | 9.30 | 9.35 | 9.39 | 9.48 | 9.56 | 9.74 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | busy | 9.50 | 9.51 | 9.54 | 9.58 | 9.63 | 9.67 | 9.76 | 9.85 | 10.02* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | busy | 14.16* | 14.18* | 14.20* | 14.25* | 14.29* | 14.33* | 14.42* | 14.51* | 14.68* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | lower | median | 11.70* | 11.72* | 11.74* | 11.79* | 11.83* | 11.88* | 11.96* | 12.05* | 12.23* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | median | 12.06* | 12.07* | 12.10* | 12.14* | 12.19* | 12.23* | 12.32* | 12.41* | 12.58* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | median | 18.45* | 18.47* | 18.50* | 18.54* | 18.58* | 18.63* | 18.72* | 18.80* | 18.98* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | lower | quiet | 11.92* | 11.94* | 11.96* | 12.01* | 12.05* | 12.10* | 12.18* | 12.27* | 12.45* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | quiet | 12.34* | 12.36* | 12.39* | 12.43* | 12.47* | 12.52* | 12.61* | 12.69* | 12.87* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | quiet | 18.96* | 18.98* | 19.01* | 19.05* | 19.10* | 19.14* | 19.23* | 19.32* | 19.49* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 0.2 | lower | busy | 12.39* | 12.41* | 12.43* | 12.47* | 12.52* | 12.56* | 12.64* | 12.73* | 12.90* | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | upper | busy | 12.81* | 12.83* | 12.86* | 12.90* | 12.94* | 12.98* | 13.07* | 13.15* | 13.32* | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | busy | 17.33* | 17.35* | 17.37* | 17.42* | 17.46* | 17.50* | 17.59* | 17.67* | 17.84* | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | lower | median | 14.30* | 14.31* | 14.34* | 14.38* | 14.42* | 14.46* | 14.53* | 14.61* | 14.77* | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | upper | median | 14.84* | 14.85* | 14.88* | 14.92* | 14.96* | 14.99* | 15.07* | 15.15* | 15.31* | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | median | 21.05* | 21.07* | 21.09* | 21.13* | 21.17* | 21.21* | 21.29* | 21.36* | 21.52* | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | lower | quiet | 14.44* | 14.46* | 14.48* | 14.53* | 14.57* | 14.61* | 14.69* | 14.77* | 14.93* | +0.16 | +0.48 | 0 / 0 |
| six seller sum | 0.2 | upper | quiet | 15.05* | 15.07* | 15.09* | 15.13* | 15.17* | 15.21* | 15.29* | 15.37* | 15.53* | +0.16 | +0.48 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | quiet | 21.49* | 21.50* | 21.53* | 21.57* | 21.61* | 21.65* | 21.73* | 21.81* | 21.97* | +0.16 | +0.48 | 0 / 0 |
| BlockRun | 1 | lower | busy | 48.26* | 48.28* | 48.31* | 48.35* | 48.39* | 48.44* | 48.52* | 48.61* | 48.78* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | upper | busy | 48.30* | 48.32* | 48.34* | 48.38* | 48.43* | 48.47* | 48.56* | 48.64* | 48.81* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | facilitator gas | busy | 61.81* | 61.83* | 61.86* | 61.90* | 61.94* | 61.99* | 62.07* | 62.16* | 62.33* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | lower | median | 35.42* | 35.43* | 35.45* | 35.48* | 35.51* | 35.54* | 35.60* | 35.66* | 35.78* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | upper | median | 35.45* | 35.46* | 35.48* | 35.51* | 35.54* | 35.57* | 35.63* | 35.69* | 35.81* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | facilitator gas | median | 39.26* | 39.27* | 39.29* | 39.32* | 39.35* | 39.38* | 39.44* | 39.50* | 39.62* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | lower | quiet | 3.91 | 3.92 | 3.94 | 3.98 | 4.02 | 4.06 | 4.14 | 4.21 | 4.37 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 1 | upper | quiet | 4.02 | 4.04 | 4.06 | 4.10 | 4.14 | 4.17 | 4.25 | 4.33 | 4.48 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 1 | facilitator gas | quiet | 5.42 | 5.44 | 5.46 | 5.50 | 5.54 | 5.57 | 5.65 | 5.73 | 5.88 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 0.2 | lower | busy | 101.32* | 101.34* | 101.36* | 101.41* | 101.45* | 101.49* | 101.58* | 101.66* | 101.83* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | upper | busy | 101.47* | 101.49* | 101.52* | 101.56* | 101.60* | 101.64* | 101.73* | 101.81* | 101.98* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | busy | 114.87* | 114.89* | 114.91* | 114.96* | 115.00* | 115.04* | 115.13* | 115.21* | 115.38* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | lower | median | 79.92* | 79.93* | 79.94* | 79.96* | 79.99* | 80.01* | 80.05* | 80.10* | 80.19* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | upper | median | 80.00* | 80.01* | 80.02* | 80.05* | 80.07* | 80.09* | 80.14* | 80.18* | 80.27* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | median | 83.75* | 83.76* | 83.78* | 83.80* | 83.82* | 83.84* | 83.89* | 83.94* | 84.03* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | lower | quiet | 5.91 | 5.92 | 5.93 | 5.95 | 5.96 | 5.98 | 6.02 | 6.05 | 6.13 | +0.07 | +0.22 | 0 / 0 |
| BlockRun | 0.2 | upper | quiet | 6.06 | 6.07 | 6.08 | 6.10 | 6.11 | 6.13 | 6.17 | 6.20 | 6.28 | +0.07 | +0.22 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | quiet | 7.42 | 7.43 | 7.44 | 7.46 | 7.48 | 7.50 | 7.53 | 7.57 | 7.64 | +0.07 | +0.22 | 0 / 0 |

*  10% over.

## 4. deduction cV cost: old model V0 (supplement Table, P8)

| set | V | estimated | window | c 1 | c 2 | c 4 | c 2 − c 1 (%p) | c 4 − c 1 (%p) | k changed seller (c 2 / c 4) |
|---|---|---|---|---|---|---|---|---|---|
| six seller sum | 1 | lower | busy | 4.84 | 5.02 | 5.37 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | busy | 6.84 | 7.01 | 7.36 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | busy | 9.79 | 9.96 | 10.31* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | lower | median | 5.97 | 6.15 | 6.50 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | median | 8.51 | 8.69 | 9.04 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | median | 12.72* | 12.90* | 13.25* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | lower | quiet | 5.84 | 6.02 | 6.37 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | upper | quiet | 8.10 | 8.28 | 8.63 | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 1 | facilitator gas | quiet | 12.88* | 13.06* | 13.41* | +0.18 | +0.53 | 0 / 0 |
| six seller sum | 0.2 | lower | busy | 8.05 | 8.22 | 8.56 | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | upper | busy | 10.20* | 10.37* | 10.71* | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | busy | 12.99* | 13.16* | 13.50* | +0.17 | +0.51 | 0 / 0 |
| six seller sum | 0.2 | lower | median | 8.59 | 8.75 | 9.06 | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | upper | median | 11.34* | 11.49* | 11.80* | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | median | 15.35* | 15.50* | 15.81* | +0.16 | +0.47 | 0 / 0 |
| six seller sum | 0.2 | lower | quiet | 8.39 | 8.55 | 8.87 | +0.16 | +0.48 | 0 / 0 |
| six seller sum | 0.2 | upper | quiet | 10.85* | 11.01* | 11.34* | +0.16 | +0.48 | 0 / 0 |
| six seller sum | 0.2 | facilitator gas | quiet | 15.43* | 15.60* | 15.92* | +0.16 | +0.48 | 0 / 0 |
| BlockRun | 1 | lower | busy | 42.05* | 42.22* | 42.56* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | upper | busy | 42.10* | 42.27* | 42.62* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | facilitator gas | busy | 55.60* | 55.77* | 56.11* | +0.17 | +0.52 | 0 / 0 |
| BlockRun | 1 | lower | median | 33.60* | 33.72* | 33.96* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | upper | median | 33.64* | 33.76* | 34.00* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | facilitator gas | median | 37.44* | 37.56* | 37.80* | +0.12 | +0.36 | 0 / 0 |
| BlockRun | 1 | lower | quiet | 2.70 | 2.85 | 3.16 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 1 | upper | quiet | 3.10 | 3.25 | 3.56 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 1 | facilitator gas | quiet | 4.21 | 4.37 | 4.68 | +0.15 | +0.46 | 0 / 0 |
| BlockRun | 0.2 | lower | busy | 95.13* | 95.30* | 95.64* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | upper | busy | 95.32* | 95.49* | 95.83* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | busy | 108.68* | 108.85* | 109.19* | +0.17 | +0.51 | 0 / 0 |
| BlockRun | 0.2 | lower | median | 78.11* | 78.20* | 78.38* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | upper | median | 78.22* | 78.31* | 78.49* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | median | 81.95* | 82.04* | 82.22* | +0.09 | +0.27 | 0 / 0 |
| BlockRun | 0.2 | lower | quiet | 4.71 | 4.78 | 4.93 | +0.07 | +0.22 | 0 / 0 |
| BlockRun | 0.2 | upper | quiet | 5.15 | 5.22 | 5.37 | +0.07 | +0.22 | 0 / 0 |
| BlockRun | 0.2 | facilitator gas | quiet | 6.23 | 6.30 | 6.44 | +0.07 | +0.22 | 0 / 0 |

*  10% over.

## 5. increment decomposition (V1u, c 2 − c 1, %p): deduction term / capital term / freeze term

| set | V | estimated | window | deduction | capital | freeze | sum |
|---|---|---|---|---|---|---|---|
| six seller sum | 1 | lower | busy | +0.173 | +0.002 | +0.000 | +0.175 |
| six seller sum | 1 | upper | busy | +0.173 | +0.002 | +0.000 | +0.175 |
| six seller sum | 1 | facilitator gas | busy | +0.173 | +0.002 | +0.000 | +0.175 |
| six seller sum | 1 | lower | median | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 1 | upper | median | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 1 | facilitator gas | median | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 1 | lower | quiet | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 1 | upper | quiet | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 1 | facilitator gas | quiet | +0.173 | +0.003 | +0.000 | +0.176 |
| six seller sum | 0.2 | lower | busy | +0.169 | +0.000 | +0.000 | +0.170 |
| six seller sum | 0.2 | upper | busy | +0.169 | +0.000 | +0.000 | +0.170 |
| six seller sum | 0.2 | facilitator gas | busy | +0.169 | +0.000 | +0.000 | +0.170 |
| six seller sum | 0.2 | lower | median | +0.156 | +0.001 | +0.000 | +0.156 |
| six seller sum | 0.2 | upper | median | +0.156 | +0.001 | +0.000 | +0.156 |
| six seller sum | 0.2 | facilitator gas | median | +0.156 | +0.001 | +0.000 | +0.156 |
| six seller sum | 0.2 | lower | quiet | +0.160 | +0.001 | +0.000 | +0.161 |
| six seller sum | 0.2 | upper | quiet | +0.160 | +0.001 | +0.000 | +0.161 |
| six seller sum | 0.2 | facilitator gas | quiet | +0.160 | +0.001 | +0.000 | +0.161 |
| BlockRun | 1 | lower | busy | +0.172 | +0.000 | +0.000 | +0.172 |
| BlockRun | 1 | upper | busy | +0.172 | +0.000 | +0.000 | +0.172 |
| BlockRun | 1 | facilitator gas | busy | +0.172 | +0.000 | +0.000 | +0.172 |
| BlockRun | 1 | lower | median | +0.121 | +0.000 | +0.000 | +0.121 |
| BlockRun | 1 | upper | median | +0.121 | +0.000 | +0.000 | +0.121 |
| BlockRun | 1 | facilitator gas | median | +0.121 | +0.000 | +0.000 | +0.121 |
| BlockRun | 1 | lower | quiet | +0.154 | +0.000 | +0.000 | +0.154 |
| BlockRun | 1 | upper | quiet | +0.154 | +0.000 | +0.000 | +0.154 |
| BlockRun | 1 | facilitator gas | quiet | +0.154 | +0.000 | +0.000 | +0.154 |
| BlockRun | 0.2 | lower | busy | +0.169 | +0.000 | +0.000 | +0.169 |
| BlockRun | 0.2 | upper | busy | +0.169 | +0.000 | +0.000 | +0.169 |
| BlockRun | 0.2 | facilitator gas | busy | +0.169 | +0.000 | +0.000 | +0.169 |
| BlockRun | 0.2 | lower | median | +0.090 | +0.000 | +0.000 | +0.090 |
| BlockRun | 0.2 | upper | median | +0.090 | +0.000 | +0.000 | +0.090 |
| BlockRun | 0.2 | facilitator gas | median | +0.090 | +0.000 | +0.000 | +0.090 |
| BlockRun | 0.2 | lower | quiet | +0.072 | +0.000 | +0.000 | +0.072 |
| BlockRun | 0.2 | upper | quiet | +0.072 | +0.000 | +0.000 | +0.072 |
| BlockRun | 0.2 | facilitator gas | quiet | +0.072 | +0.000 | +0.000 | +0.072 |
