# K12 output (k12.py)

K12_calc-rules.md SHA-256 absent. this document this run before was written(K12_results.md same value recorded).

| input | SHA-256 prior 8 |
|---|---|
| docs/05_run-evidence/R7R8/out/R9/R9-5/price_cache.json | ec267a05 |
| docs/11_journal/F/data-review/target_sellers_all_summary.csv | 03cbc0f0 |
| docs/11_journal/F/data-review/target_sellers_values.csv | d7127938 |
| data/processed/agg_2026-10-21/epochs_median.csv.gz | b8f1ecaf |
| data/processed/agg_2026-10-21/epochs_busy.csv.gz | 0a4da864 |
| docs/11_journal/G11_gas/logs/p5_l1fee.tsv.gz | 19b8abff |
| docs/11_journal/G11_gas/G11_gas.md | absent |
| docs/11_journal/K11/k11b_output.md | 71fee7e6 |
| docs/11_journal/K11/k11b.py | d887772c |
| docs/11_journal/K11/K11b_settings.md | absent |
| docs/11_journal/rule10-candidate/F1_seller-stage-classes.csv | absent |

## 1. K11b reproduction: bundle size N = 1 this file k11b_output.md cells as is outputs

| Table | cell count | equal |
|---|---|---|
| 5 (sec.) seller row(N, S: k, lower, upper, lower carry-over) | 336 | 336 |
| 5 (sec.) set row(N, S, S-d, S-120: lower, upper, lower carry-over) | 240 | 240 |
| 6 (sec.) V grid | 70 | 70 |

N = 1 k11b_output.md 646cell among 646cells as is outputs.

## 2. bundle gas constant (sketch value; G11 in row calculation)

| constant | value | basis |
|---|---|---|
| bundle header WRAP (per transaction) | 3,252 gas | bundle P = 1, 32 items 885,939 − self submission 32 items 882,687 (G11 3.1 (sec.)) |
| transaction default | 21,000 gas | dividing share. G11 3.1 (sec.) read one 2 |
| scenario S per unit change δ | −21,000 + 24,252 f | f = 1/m (P1) |
| scenario M per unit change (m = 1, 2, 4, 8) | +0, -6991, -6745, +4452 | P = 2, 4, 8 transaction gas / P − self submission 32 items (G11 3.1 (sec.)) |
| scenario Z stored compression | −66,300 gas (N regardless) | 3 × 22,100. rule change required assumption |
| release a (sketch) | 0.6000 | G11 6 (sec.) caveat 0.6~0.7x interval among m = 8 0.65 |
| release a (measured as is) | 0.5837 | (531,147 − 108,062) / 7 = 60440.7 gas / direct release 103,552 |
| sample value | 1/N (P1) | per set per epoch request 48,669, accepted 78,301 gas (G11 3.2 (sec.)) |
| transaction gas upper | 16,777,216 | 2^24 |

## 3. main scenario(anchor S, release a 0.6, concurrent activity P1; bundle gas sketch value) mode N, V 1

### Table 1. N per median seller cost (T01t seller median, revenue relative to)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 24.18% | 37.80% | 47.45% | 70.92% | 73.40% | 111.34% |
| 4 | 19.61% | 24.86% | 33.75% | 39.85% | 51.37% | 61.37% |
| 16 | 18.44% | 21.59% | 30.25% | 32.01% | 45.74% | 48.75% |
| 64 | 18.15% | 20.79% | 29.37% | 30.04% | 44.33% | 45.60% |

### Table 2. small seller three cost

| seller | N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|---|
| CoinStats(0.01 or less) | 1 | 301.21% | 447.59% | 488.07% | 728.04% | 380.22% | 563.38% |
| CoinStats(0.01 or less) | 4 | 216.91% | 256.38% | 351.46% | 418.19% | 285.38% | 348.27% |
| CoinStats(0.01 or less) | 16 | 195.37% | 208.10% | 316.54% | 339.95% | 261.14% | 293.96% |
| CoinStats(0.01 or less) | 64 | 189.98% | 196.03% | 307.81% | 320.40% | 255.09% | 280.39% |
| Exa(0.001 or less) | 1 | 806.14% | 1412.38% | 788.07% | 1402.50% | 929.62% | 1689.30% |
| Exa(0.001 or less) | 4 | 552.74% | 757.90% | 540.21% | 752.61% | 632.92% | 900.57% |
| Exa(0.001 or less) | 16 | 487.77% | 592.66% | 476.64% | 588.53% | 556.79% | 701.43% |
| Exa(0.001 or less) | 64 | 471.53% | 551.35% | 460.74% | 547.51% | 537.76% | 651.65% |
| StableApify | 1 | 19.66% | 28.42% | 51.28% | 77.11% | 73.40% | 111.23% |
| StableApify | 4 | 14.55% | 16.83% | 36.25% | 43.04% | 51.67% | 61.93% |
| StableApify | 16 | 13.25% | 13.90% | 32.41% | 34.44% | 46.11% | 49.49% |
| StableApify | 64 | 12.92% | 13.17% | 31.45% | 32.29% | 44.72% | 46.37% |

### Table 3. 10% within falling seller count (seven among)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1 | 2 | 2 |
| 4 | 1 | 1 | 1 | 1 | 2 | 2 |
| 16 | 1 | 1 | 1 | 1 | 2 | 2 |
| 64 | 1 | 1 | 1 | 1 | 2 | 2 |

seven seller whole(lower / upper):

| window | seller | N 1 | N 4 | N 16 | N 64 |
|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 3.67% / 4.89% | 3.29% / 3.79% | 3.20% / 3.51% | 3.17% / 3.44% |
| busy | OneSource | 22.67% / 29.27% | 20.22% / 22.76% | 19.60% / 21.12% | 19.46% / 20.72% |
| busy | CoinMarketCap | 25.69% / 46.32% | 19.00% / 26.96% | 17.28% / 22.07% | 16.85% / 20.85% |
| busy | StableApify | 19.66% / 28.42% | 14.55% / 16.83% | 13.25% / 13.90% | 12.92% / 13.17% |
| busy | Exa(0.001 or less) | 806.14% / 1412.38% | 552.74% / 757.90% | 487.77% / 592.66% | 471.53% / 551.35% |
| busy | CoinStats(0.01 or less) | 301.21% / 447.59% | 216.91% / 256.38% | 195.37% / 208.10% | 189.98% / 196.03% |
| busy | BlockRun | 42.05% / 42.10% | 42.04% / 42.08% | 42.04% / 42.07% | 42.04% / 42.07% |
| median | StableEnrich(Out candidates excluded) | 4.00% / 5.67% | 3.49% / 4.15% | 3.36% / 3.77% | 3.33% / 3.68% |
| median | OneSource | 29.57% / 41.79% | 25.73% / 30.63% | 24.74% / 27.81% | 24.51% / 27.13% |
| median | CoinMarketCap | 43.61% / 64.72% | 31.24% / 36.66% | 28.08% / 29.57% | 27.29% / 27.80% |
| median | StableApify | 51.28% / 77.11% | 36.25% / 43.04% | 32.41% / 34.44% | 31.45% / 32.29% |
| median | Exa(0.001 or less) | 788.07% / 1402.50% | 540.21% / 752.61% | 476.64% / 588.53% | 460.74% / 547.51% |
| median | CoinStats(0.01 or less) | 488.07% / 728.04% | 351.46% / 418.19% | 316.54% / 339.95% | 307.81% / 320.40% |
| median | BlockRun | 33.60% / 33.64% | 33.59% / 33.62% | 33.59% / 33.62% | 33.59% / 33.62% |
| quiet | StableEnrich(Out candidates excluded) | 4.51% / 6.04% | 4.03% / 4.64% | 3.91% / 4.29% | 3.88% / 4.20% |
| quiet | OneSource | 20.15% / 29.42% | 17.17% / 20.91% | 16.41% / 18.76% | 16.23% / 18.23% |
| quiet | CoinMarketCap | 73.40% / 111.45% | 51.07% / 60.81% | 45.36% / 48.02% | 43.94% / 44.83% |
| quiet | StableApify | 73.40% / 111.23% | 51.67% / 61.93% | 46.11% / 49.49% | 44.72% / 46.37% |
| quiet | Exa(0.001 or less) | 929.62% / 1689.30% | 632.92% / 900.57% | 556.79% / 701.43% | 537.76% / 651.65% |
| quiet | CoinStats(0.01 or less) | 380.22% / 563.38% | 285.38% / 348.27% | 261.14% / 293.96% | 255.09% / 280.39% |
| quiet | BlockRun | 2.70% / 3.10% | 2.58% / 2.75% | 2.55% / 2.66% | 2.54% / 2.64% |

### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)

| window | target | N | lower | upper | N = 1 relative to lower change(%p) |
|---|---|---|---|---|---|
| busy | T01t pooled | 1 | 4.84% | 6.84% | +0.00 |
| busy | T01t pooled | 4 | 4.20% | 4.98% | -0.65 |
| busy | T01t pooled | 16 | 4.03% | 4.51% | -0.82 |
| busy | T01t pooled | 64 | 3.99% | 4.39% | -0.86 |
| busy | BlockRun | 1 | 42.05% | 42.10% | +0.00 |
| busy | BlockRun | 4 | 42.04% | 42.08% | -0.01 |
| busy | BlockRun | 16 | 42.04% | 42.07% | -0.01 |
| busy | BlockRun | 64 | 42.04% | 42.07% | -0.01 |
| busy | StableEnrich(Out candidates excluded) | 1 | 3.67% | 4.89% | +0.00 |
| busy | StableEnrich(Out candidates excluded) | 4 | 3.29% | 3.79% | -0.38 |
| busy | StableEnrich(Out candidates excluded) | 16 | 3.20% | 3.51% | -0.47 |
| busy | StableEnrich(Out candidates excluded) | 64 | 3.17% | 3.44% | -0.50 |
| median | T01t pooled | 1 | 5.97% | 8.51% | +0.00 |
| median | T01t pooled | 4 | 5.15% | 6.16% | -0.82 |
| median | T01t pooled | 16 | 4.94% | 5.56% | -1.03 |
| median | T01t pooled | 64 | 4.89% | 5.41% | -1.08 |
| median | BlockRun | 1 | 33.60% | 33.64% | +0.00 |
| median | BlockRun | 4 | 33.59% | 33.62% | -0.01 |
| median | BlockRun | 16 | 33.59% | 33.62% | -0.01 |
| median | BlockRun | 64 | 33.59% | 33.62% | -0.01 |
| median | StableEnrich(Out candidates excluded) | 1 | 4.00% | 5.67% | +0.00 |
| median | StableEnrich(Out candidates excluded) | 4 | 3.49% | 4.15% | -0.52 |
| median | StableEnrich(Out candidates excluded) | 16 | 3.36% | 3.77% | -0.65 |
| median | StableEnrich(Out candidates excluded) | 64 | 3.33% | 3.68% | -0.68 |
| quiet | T01t pooled | 1 | 5.84% | 8.10% | +0.00 |
| quiet | T01t pooled | 4 | 5.10% | 5.99% | -0.74 |
| quiet | T01t pooled | 16 | 4.91% | 5.45% | -0.93 |
| quiet | T01t pooled | 64 | 4.86% | 5.32% | -0.98 |
| quiet | BlockRun | 1 | 2.70% | 3.10% | +0.00 |
| quiet | BlockRun | 4 | 2.58% | 2.75% | -0.12 |
| quiet | BlockRun | 16 | 2.55% | 2.66% | -0.15 |
| quiet | BlockRun | 64 | 2.54% | 2.64% | -0.16 |
| quiet | StableEnrich(Out candidates excluded) | 1 | 4.51% | 6.04% | +0.00 |
| quiet | StableEnrich(Out candidates excluded) | 4 | 4.03% | 4.64% | -0.48 |
| quiet | StableEnrich(Out candidates excluded) | 16 | 3.91% | 4.29% | -0.60 |
| quiet | StableEnrich(Out candidates excluded) | 64 | 3.88% | 4.20% | -0.63 |

## 4. main scenario(anchor S, release a 0.6, concurrent activity P1; bundle gas sketch value) mode N, V 0.2

### Table 1. N per median seller cost (T01t seller median, revenue relative to)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 27.61% | 41.94% | 47.79% | 71.41% | 73.40% | 111.48% |
| 4 | 23.04% | 29.00% | 34.10% | 40.63% | 51.37% | 61.51% |
| 16 | 21.87% | 25.74% | 31.65% | 34.92% | 45.74% | 48.89% |
| 64 | 21.58% | 24.93% | 31.06% | 33.50% | 44.33% | 45.74% |

### Table 2. small seller three cost

| seller | N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|---|
| CoinStats(0.01 or less) | 1 | 295.09% | 441.61% | 472.48% | 712.60% | 351.19% | 534.49% |
| CoinStats(0.01 or less) | 4 | 210.80% | 250.40% | 335.88% | 402.74% | 256.35% | 319.38% |
| CoinStats(0.01 or less) | 16 | 189.25% | 202.12% | 300.96% | 324.51% | 232.11% | 265.07% |
| CoinStats(0.01 or less) | 64 | 183.86% | 190.05% | 292.23% | 304.95% | 226.06% | 251.50% |
| Exa(0.001 or less) | 1 | 805.04% | 1411.42% | 787.20% | 1401.78% | 928.63% | 1688.45% |
| Exa(0.001 or less) | 4 | 551.64% | 756.94% | 539.34% | 751.88% | 631.93% | 899.72% |
| Exa(0.001 or less) | 16 | 486.67% | 591.70% | 475.77% | 587.80% | 555.80% | 700.58% |
| Exa(0.001 or less) | 64 | 470.43% | 550.39% | 459.88% | 546.78% | 536.77% | 650.80% |
| StableApify | 1 | 20.37% | 29.26% | 51.40% | 77.37% | 72.89% | 110.85% |
| StableApify | 4 | 15.26% | 17.67% | 36.38% | 43.30% | 51.15% | 61.56% |
| StableApify | 16 | 13.95% | 14.75% | 32.54% | 34.70% | 45.60% | 49.11% |
| StableApify | 64 | 13.63% | 14.02% | 31.58% | 32.55% | 44.21% | 46.00% |

### Table 3. 10% within falling seller count (seven among)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1 | 2 | 2 |
| 4 | 1 | 1 | 1 | 1 | 2 | 2 |
| 16 | 1 | 1 | 1 | 1 | 2 | 2 |
| 64 | 1 | 1 | 1 | 1 | 2 | 2 |

seven seller whole(lower / upper):

| window | seller | N 1 | N 4 | N 16 | N 64 |
|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 6.89% / 8.25% | 6.51% / 7.14% | 6.42% / 6.86% | 6.39% / 6.79% |
| busy | OneSource | 28.61% / 36.50% | 26.16% / 29.99% | 25.54% / 28.35% | 25.40% / 27.95% |
| busy | CoinMarketCap | 26.61% / 47.38% | 19.92% / 28.02% | 18.20% / 23.13% | 17.77% / 21.91% |
| busy | StableApify | 20.37% / 29.26% | 15.26% / 17.67% | 13.95% / 14.75% | 13.63% / 14.02% |
| busy | Exa(0.001 or less) | 805.04% / 1411.42% | 551.64% / 756.94% | 486.67% / 591.70% | 470.43% / 550.39% |
| busy | CoinStats(0.01 or less) | 295.09% / 441.61% | 210.80% / 250.40% | 189.25% / 202.12% | 183.86% / 190.05% |
| busy | BlockRun | 95.13% / 95.32% | 95.13% / 95.30% | 95.12% / 95.30% | 95.12% / 95.30% |
| median | StableEnrich(Out candidates excluded) | 6.39% / 8.17% | 5.87% / 6.66% | 5.74% / 6.28% | 5.71% / 6.18% |
| median | OneSource | 35.61% / 49.11% | 31.76% / 37.96% | 30.77% / 35.14% | 30.55% / 34.45% |
| median | CoinMarketCap | 44.19% / 65.44% | 31.82% / 37.37% | 28.65% / 30.29% | 27.86% / 28.52% |
| median | StableApify | 51.40% / 77.37% | 36.38% / 43.30% | 32.54% / 34.70% | 31.58% / 32.55% |
| median | Exa(0.001 or less) | 787.20% / 1401.78% | 539.34% / 751.88% | 475.77% / 587.80% | 459.88% / 546.78% |
| median | CoinStats(0.01 or less) | 472.48% / 712.60% | 335.88% / 402.74% | 300.96% / 324.51% | 292.23% / 304.95% |
| median | BlockRun | 78.11% / 78.22% | 78.11% / 78.20% | 78.10% / 78.20% | 78.10% / 78.20% |
| quiet | StableEnrich(Out candidates excluded) | 6.82% / 8.48% | 6.34% / 7.08% | 6.22% / 6.73% | 6.19% / 6.64% |
| quiet | OneSource | 26.17% / 36.73% | 23.19% / 28.21% | 22.43% / 26.06% | 22.25% / 25.53% |
| quiet | CoinMarketCap | 73.91% / 112.10% | 51.58% / 61.46% | 45.88% / 48.67% | 44.45% / 45.48% |
| quiet | StableApify | 72.89% / 110.85% | 51.15% / 61.56% | 45.60% / 49.11% | 44.21% / 46.00% |
| quiet | Exa(0.001 or less) | 928.63% / 1688.45% | 631.93% / 899.72% | 555.80% / 700.58% | 536.77% / 650.80% |
| quiet | CoinStats(0.01 or less) | 351.19% / 534.49% | 256.35% / 319.38% | 232.11% / 265.07% | 226.06% / 251.50% |
| quiet | BlockRun | 4.71% / 5.15% | 4.59% / 4.80% | 4.56% / 4.72% | 4.55% / 4.69% |

### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)

| window | target | N | lower | upper | N = 1 relative to lower change(%p) |
|---|---|---|---|---|---|
| busy | T01t pooled | 1 | 8.05% | 10.20% | +0.00 |
| busy | T01t pooled | 4 | 7.40% | 8.34% | -0.65 |
| busy | T01t pooled | 16 | 7.23% | 7.87% | -0.82 |
| busy | T01t pooled | 64 | 7.19% | 7.75% | -0.86 |
| busy | BlockRun | 1 | 95.13% | 95.32% | +0.00 |
| busy | BlockRun | 4 | 95.13% | 95.30% | -0.01 |
| busy | BlockRun | 16 | 95.12% | 95.30% | -0.01 |
| busy | BlockRun | 64 | 95.12% | 95.30% | -0.01 |
| busy | StableEnrich(Out candidates excluded) | 1 | 6.89% | 8.25% | +0.00 |
| busy | StableEnrich(Out candidates excluded) | 4 | 6.51% | 7.14% | -0.38 |
| busy | StableEnrich(Out candidates excluded) | 16 | 6.42% | 6.86% | -0.47 |
| busy | StableEnrich(Out candidates excluded) | 64 | 6.39% | 6.79% | -0.50 |
| median | T01t pooled | 1 | 8.59% | 11.34% | +0.00 |
| median | T01t pooled | 4 | 7.77% | 8.98% | -0.82 |
| median | T01t pooled | 16 | 7.56% | 8.38% | -1.03 |
| median | T01t pooled | 64 | 7.52% | 8.24% | -1.08 |
| median | BlockRun | 1 | 78.11% | 78.22% | +0.00 |
| median | BlockRun | 4 | 78.11% | 78.20% | -0.01 |
| median | BlockRun | 16 | 78.10% | 78.20% | -0.01 |
| median | BlockRun | 64 | 78.10% | 78.20% | -0.01 |
| median | StableEnrich(Out candidates excluded) | 1 | 6.39% | 8.17% | +0.00 |
| median | StableEnrich(Out candidates excluded) | 4 | 5.87% | 6.66% | -0.52 |
| median | StableEnrich(Out candidates excluded) | 16 | 5.74% | 6.28% | -0.65 |
| median | StableEnrich(Out candidates excluded) | 64 | 5.71% | 6.18% | -0.68 |
| quiet | T01t pooled | 1 | 8.39% | 10.85% | +0.00 |
| quiet | T01t pooled | 4 | 7.65% | 8.74% | -0.74 |
| quiet | T01t pooled | 16 | 7.46% | 8.20% | -0.93 |
| quiet | T01t pooled | 64 | 7.41% | 8.07% | -0.98 |
| quiet | BlockRun | 1 | 4.71% | 5.15% | +0.00 |
| quiet | BlockRun | 4 | 4.59% | 4.80% | -0.12 |
| quiet | BlockRun | 16 | 4.56% | 4.72% | -0.15 |
| quiet | BlockRun | 64 | 4.55% | 4.69% | -0.16 |
| quiet | StableEnrich(Out candidates excluded) | 1 | 6.82% | 8.48% | +0.00 |
| quiet | StableEnrich(Out candidates excluded) | 4 | 6.34% | 7.08% | -0.48 |
| quiet | StableEnrich(Out candidates excluded) | 16 | 6.22% | 6.73% | -0.60 |
| quiet | StableEnrich(Out candidates excluded) | 64 | 6.19% | 6.64% | -0.63 |

## 5. measured scenario(anchor M(G11 measured, 8place or less), release a 0.5837; bundle gas G11 see implementation measured) mode N, V 1

### Table 1. N per median seller cost (T01t seller median, revenue relative to)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 24.18% | 37.80% | 47.45% | 70.92% | 73.40% | 111.34% |
| 4 | 19.92% | 25.13% | 34.39% | 40.49% | 52.40% | 62.40% |
| 16 | 19.39% | 22.58% | 32.63% | 34.39% | 49.57% | 52.58% |
| 64 | 19.15% | 21.90% | 32.06% | 32.74% | 48.66% | 49.93% |

### Table 2. small seller three cost

| seller | N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|---|
| CoinStats(0.01 or less) | 1 | 301.21% | 447.59% | 488.07% | 728.04% | 380.22% | 563.38% |
| CoinStats(0.01 or less) | 4 | 220.87% | 260.33% | 357.86% | 424.59% | 289.83% | 352.72% |
| CoinStats(0.01 or less) | 16 | 210.02% | 222.75% | 340.28% | 363.69% | 277.62% | 310.45% |
| CoinStats(0.01 or less) | 64 | 206.54% | 212.60% | 334.65% | 347.24% | 273.72% | 299.02% |
| Exa(0.001 or less) | 1 | 806.14% | 1412.38% | 788.07% | 1402.50% | 929.62% | 1689.30% |
| Exa(0.001 or less) | 4 | 567.70% | 771.43% | 555.22% | 766.05% | 651.30% | 916.87% |
| Exa(0.001 or less) | 16 | 536.66% | 642.81% | 525.05% | 638.33% | 615.40% | 761.86% |
| Exa(0.001 or less) | 64 | 524.77% | 608.05% | 513.24% | 603.81% | 601.07% | 719.97% |
| StableApify | 1 | 19.66% | 28.42% | 51.28% | 77.11% | 73.40% | 111.23% |
| StableApify | 4 | 14.79% | 17.07% | 36.96% | 43.74% | 52.69% | 62.95% |
| StableApify | 16 | 14.13% | 14.79% | 35.03% | 37.05% | 49.89% | 53.26% |
| StableApify | 64 | 13.92% | 14.18% | 34.41% | 35.24% | 48.99% | 50.64% |

### Table 3. 10% within falling seller count (seven among)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1 | 2 | 2 |
| 4 | 1 | 1 | 1 | 1 | 2 | 2 |
| 16 | 1 | 1 | 1 | 1 | 2 | 2 |
| 64 | 1 | 1 | 1 | 1 | 2 | 2 |

seven seller whole(lower / upper):

| window | seller | N 1 | N 4 | N 16 | N 64 |
|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 3.67% / 4.89% | 3.32% / 3.81% | 3.28% / 3.59% | 3.26% / 3.53% |
| busy | OneSource | 22.67% / 29.27% | 20.38% / 22.89% | 20.08% / 21.62% | 19.96% / 21.27% |
| busy | CoinMarketCap | 25.69% / 46.32% | 19.47% / 27.36% | 18.70% / 23.55% | 18.34% / 22.52% |
| busy | StableApify | 19.66% / 28.42% | 14.79% / 17.07% | 14.13% / 14.79% | 13.92% / 14.18% |
| busy | Exa(0.001 or less) | 806.14% / 1412.38% | 567.70% / 771.43% | 536.66% / 642.81% | 524.77% / 608.05% |
| busy | CoinStats(0.01 or less) | 301.21% / 447.59% | 220.87% / 260.33% | 210.02% / 222.75% | 206.54% / 212.60% |
| busy | BlockRun | 42.05% / 42.10% | 42.04% / 42.08% | 42.04% / 42.07% | 42.04% / 42.07% |
| median | StableEnrich(Out candidates excluded) | 4.00% / 5.67% | 3.53% / 4.19% | 3.47% / 3.89% | 3.44% / 3.81% |
| median | OneSource | 29.57% / 41.79% | 26.00% / 30.86% | 25.55% / 28.67% | 25.35% / 28.07% |
| median | CoinMarketCap | 43.61% / 64.72% | 31.82% / 37.24% | 30.23% / 31.72% | 29.72% / 30.23% |
| median | StableApify | 51.28% / 77.11% | 36.96% / 43.74% | 35.03% / 37.05% | 34.41% / 35.24% |
| median | Exa(0.001 or less) | 788.07% / 1402.50% | 555.22% / 766.05% | 525.05% / 638.33% | 513.24% / 603.81% |
| median | CoinStats(0.01 or less) | 488.07% / 728.04% | 357.86% / 424.59% | 340.28% / 363.69% | 334.65% / 347.24% |
| median | BlockRun | 33.60% / 33.64% | 33.59% / 33.62% | 33.59% / 33.62% | 33.59% / 33.62% |
| quiet | StableEnrich(Out candidates excluded) | 4.51% / 6.04% | 4.06% / 4.67% | 4.01% / 4.40% | 3.98% / 4.32% |
| quiet | OneSource | 20.15% / 29.42% | 17.38% / 21.08% | 17.03% / 19.41% | 16.88% / 18.96% |
| quiet | CoinMarketCap | 73.40% / 111.45% | 52.12% / 61.86% | 49.24% / 51.90% | 48.32% / 49.21% |
| quiet | StableApify | 73.40% / 111.23% | 52.69% / 62.95% | 49.89% / 53.26% | 48.99% / 50.64% |
| quiet | Exa(0.001 or less) | 929.62% / 1689.30% | 651.30% / 916.87% | 615.40% / 761.86% | 601.07% / 719.97% |
| quiet | CoinStats(0.01 or less) | 380.22% / 563.38% | 289.83% / 352.72% | 277.62% / 310.45% | 273.72% / 299.02% |
| quiet | BlockRun | 2.70% / 3.10% | 2.59% / 2.76% | 2.58% / 2.69% | 2.57% / 2.67% |

### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)

| window | target | N | lower | upper | N = 1 relative to lower change(%p) |
|---|---|---|---|---|---|
| busy | T01t pooled | 1 | 4.84% | 6.84% | +0.00 |
| busy | T01t pooled | 4 | 4.24% | 5.02% | -0.60 |
| busy | T01t pooled | 16 | 4.16% | 4.65% | -0.68 |
| busy | T01t pooled | 64 | 4.13% | 4.55% | -0.71 |
| busy | BlockRun | 1 | 42.05% | 42.10% | +0.00 |
| busy | BlockRun | 4 | 42.04% | 42.08% | -0.01 |
| busy | BlockRun | 16 | 42.04% | 42.07% | -0.01 |
| busy | BlockRun | 64 | 42.04% | 42.07% | -0.01 |
| busy | StableEnrich(Out candidates excluded) | 1 | 3.67% | 4.89% | +0.00 |
| busy | StableEnrich(Out candidates excluded) | 4 | 3.32% | 3.81% | -0.35 |
| busy | StableEnrich(Out candidates excluded) | 16 | 3.28% | 3.59% | -0.39 |
| busy | StableEnrich(Out candidates excluded) | 64 | 3.26% | 3.53% | -0.41 |
| median | T01t pooled | 1 | 5.97% | 8.51% | +0.00 |
| median | T01t pooled | 4 | 5.21% | 6.20% | -0.76 |
| median | T01t pooled | 16 | 5.11% | 5.74% | -0.86 |
| median | T01t pooled | 64 | 5.07% | 5.62% | -0.90 |
| median | BlockRun | 1 | 33.60% | 33.64% | +0.00 |
| median | BlockRun | 4 | 33.59% | 33.62% | -0.01 |
| median | BlockRun | 16 | 33.59% | 33.62% | -0.01 |
| median | BlockRun | 64 | 33.59% | 33.62% | -0.01 |
| median | StableEnrich(Out candidates excluded) | 1 | 4.00% | 5.67% | +0.00 |
| median | StableEnrich(Out candidates excluded) | 4 | 3.53% | 4.19% | -0.48 |
| median | StableEnrich(Out candidates excluded) | 16 | 3.47% | 3.89% | -0.54 |
| median | StableEnrich(Out candidates excluded) | 64 | 3.44% | 3.81% | -0.57 |
| quiet | T01t pooled | 1 | 5.84% | 8.10% | +0.00 |
| quiet | T01t pooled | 4 | 5.15% | 6.03% | -0.69 |
| quiet | T01t pooled | 16 | 5.06% | 5.62% | -0.78 |
| quiet | T01t pooled | 64 | 5.03% | 5.50% | -0.81 |
| quiet | BlockRun | 1 | 2.70% | 3.10% | +0.00 |
| quiet | BlockRun | 4 | 2.59% | 2.76% | -0.11 |
| quiet | BlockRun | 16 | 2.58% | 2.69% | -0.12 |
| quiet | BlockRun | 64 | 2.57% | 2.67% | -0.13 |
| quiet | StableEnrich(Out candidates excluded) | 1 | 4.51% | 6.04% | +0.00 |
| quiet | StableEnrich(Out candidates excluded) | 4 | 4.06% | 4.67% | -0.44 |
| quiet | StableEnrich(Out candidates excluded) | 16 | 4.01% | 4.40% | -0.50 |
| quiet | StableEnrich(Out candidates excluded) | 64 | 3.98% | 4.32% | -0.52 |

## 6. measured scenario(anchor M(G11 measured, 8place or less), release a 0.5837; bundle gas G11 see implementation measured) mode N, V 0.2

### Table 1. N per median seller cost (T01t seller median, revenue relative to)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 27.61% | 41.94% | 47.79% | 71.41% | 73.40% | 111.48% |
| 4 | 23.35% | 29.27% | 34.74% | 41.09% | 52.40% | 62.54% |
| 16 | 22.82% | 26.73% | 33.37% | 36.65% | 49.57% | 52.72% |
| 64 | 22.58% | 26.04% | 32.96% | 35.45% | 48.66% | 50.07% |

### Table 2. small seller three cost

| seller | N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|---|
| CoinStats(0.01 or less) | 1 | 295.09% | 441.61% | 472.48% | 712.60% | 351.19% | 534.49% |
| CoinStats(0.01 or less) | 4 | 214.75% | 254.35% | 342.28% | 409.15% | 260.80% | 323.83% |
| CoinStats(0.01 or less) | 16 | 203.90% | 216.77% | 324.70% | 348.25% | 248.59% | 281.55% |
| CoinStats(0.01 or less) | 64 | 200.42% | 206.62% | 319.07% | 331.79% | 244.68% | 270.13% |
| Exa(0.001 or less) | 1 | 805.04% | 1411.42% | 787.20% | 1401.78% | 928.63% | 1688.45% |
| Exa(0.001 or less) | 4 | 566.60% | 770.47% | 554.35% | 765.32% | 650.31% | 916.02% |
| Exa(0.001 or less) | 16 | 535.56% | 641.85% | 524.18% | 637.60% | 614.41% | 761.01% |
| Exa(0.001 or less) | 64 | 523.67% | 607.08% | 512.37% | 603.08% | 600.08% | 719.12% |
| StableApify | 1 | 20.37% | 29.26% | 51.40% | 77.37% | 72.89% | 110.85% |
| StableApify | 4 | 15.50% | 17.91% | 37.08% | 44.00% | 52.17% | 62.58% |
| StableApify | 16 | 14.84% | 15.64% | 35.15% | 37.31% | 49.38% | 52.89% |
| StableApify | 64 | 14.63% | 15.02% | 34.53% | 35.50% | 48.48% | 50.27% |

### Table 3. 10% within falling seller count (seven among)

| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1 | 2 | 2 |
| 4 | 1 | 1 | 1 | 1 | 2 | 2 |
| 16 | 1 | 1 | 1 | 1 | 2 | 2 |
| 64 | 1 | 1 | 1 | 1 | 2 | 2 |

seven seller whole(lower / upper):

| window | seller | N 1 | N 4 | N 16 | N 64 |
|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 6.89% / 8.25% | 6.54% / 7.16% | 6.50% / 6.95% | 6.48% / 6.89% |
| busy | OneSource | 28.61% / 36.50% | 26.32% / 30.12% | 26.02% / 28.85% | 25.90% / 28.50% |
| busy | CoinMarketCap | 26.61% / 47.38% | 20.39% / 28.42% | 19.62% / 24.61% | 19.26% / 23.58% |
| busy | StableApify | 20.37% / 29.26% | 15.50% / 17.91% | 14.84% / 15.64% | 14.63% / 15.02% |
| busy | Exa(0.001 or less) | 805.04% / 1411.42% | 566.60% / 770.47% | 535.56% / 641.85% | 523.67% / 607.08% |
| busy | CoinStats(0.01 or less) | 295.09% / 441.61% | 214.75% / 254.35% | 203.90% / 216.77% | 200.42% / 206.62% |
| busy | BlockRun | 95.13% / 95.32% | 95.13% / 95.30% | 95.12% / 95.30% | 95.12% / 95.30% |
| median | StableEnrich(Out candidates excluded) | 6.39% / 8.17% | 5.91% / 6.69% | 5.85% / 6.39% | 5.82% / 6.31% |
| median | OneSource | 35.61% / 49.11% | 32.04% / 38.19% | 31.59% / 35.99% | 31.39% / 35.40% |
| median | CoinMarketCap | 44.19% / 65.44% | 32.40% / 37.95% | 30.80% / 32.44% | 30.29% / 30.95% |
| median | StableApify | 51.40% / 77.37% | 37.08% / 44.00% | 35.15% / 37.31% | 34.53% / 35.50% |
| median | Exa(0.001 or less) | 787.20% / 1401.78% | 554.35% / 765.32% | 524.18% / 637.60% | 512.37% / 603.08% |
| median | CoinStats(0.01 or less) | 472.48% / 712.60% | 342.28% / 409.15% | 324.70% / 348.25% | 319.07% / 331.79% |
| median | BlockRun | 78.11% / 78.22% | 78.11% / 78.20% | 78.10% / 78.20% | 78.10% / 78.20% |
| quiet | StableEnrich(Out candidates excluded) | 6.82% / 8.48% | 6.38% / 7.11% | 6.33% / 6.84% | 6.30% / 6.76% |
| quiet | OneSource | 26.17% / 36.73% | 23.40% / 28.39% | 23.05% / 26.71% | 22.90% / 26.26% |
| quiet | CoinMarketCap | 73.91% / 112.10% | 52.63% / 62.51% | 49.76% / 52.55% | 48.84% / 49.86% |
| quiet | StableApify | 72.89% / 110.85% | 52.17% / 62.58% | 49.38% / 52.89% | 48.48% / 50.27% |
| quiet | Exa(0.001 or less) | 928.63% / 1688.45% | 650.31% / 916.02% | 614.41% / 761.01% | 600.08% / 719.12% |
| quiet | CoinStats(0.01 or less) | 351.19% / 534.49% | 260.80% / 323.83% | 248.59% / 281.55% | 244.68% / 270.13% |
| quiet | BlockRun | 4.71% / 5.15% | 4.60% / 4.81% | 4.59% / 4.74% | 4.58% / 4.72% |

### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)

| window | target | N | lower | upper | N = 1 relative to lower change(%p) |
|---|---|---|---|---|---|
| busy | T01t pooled | 1 | 8.05% | 10.20% | +0.00 |
| busy | T01t pooled | 4 | 7.44% | 8.38% | -0.60 |
| busy | T01t pooled | 16 | 7.37% | 8.01% | -0.68 |
| busy | T01t pooled | 64 | 7.33% | 7.91% | -0.71 |
| busy | BlockRun | 1 | 95.13% | 95.32% | +0.00 |
| busy | BlockRun | 4 | 95.13% | 95.30% | -0.01 |
| busy | BlockRun | 16 | 95.12% | 95.30% | -0.01 |
| busy | BlockRun | 64 | 95.12% | 95.30% | -0.01 |
| busy | StableEnrich(Out candidates excluded) | 1 | 6.89% | 8.25% | +0.00 |
| busy | StableEnrich(Out candidates excluded) | 4 | 6.54% | 7.16% | -0.35 |
| busy | StableEnrich(Out candidates excluded) | 16 | 6.50% | 6.95% | -0.39 |
| busy | StableEnrich(Out candidates excluded) | 64 | 6.48% | 6.89% | -0.41 |
| median | T01t pooled | 1 | 8.59% | 11.34% | +0.00 |
| median | T01t pooled | 4 | 7.83% | 9.03% | -0.76 |
| median | T01t pooled | 16 | 7.74% | 8.56% | -0.86 |
| median | T01t pooled | 64 | 7.69% | 8.44% | -0.90 |
| median | BlockRun | 1 | 78.11% | 78.22% | +0.00 |
| median | BlockRun | 4 | 78.11% | 78.20% | -0.01 |
| median | BlockRun | 16 | 78.10% | 78.20% | -0.01 |
| median | BlockRun | 64 | 78.10% | 78.20% | -0.01 |
| median | StableEnrich(Out candidates excluded) | 1 | 6.39% | 8.17% | +0.00 |
| median | StableEnrich(Out candidates excluded) | 4 | 5.91% | 6.69% | -0.48 |
| median | StableEnrich(Out candidates excluded) | 16 | 5.85% | 6.39% | -0.54 |
| median | StableEnrich(Out candidates excluded) | 64 | 5.82% | 6.31% | -0.57 |
| quiet | T01t pooled | 1 | 8.39% | 10.85% | +0.00 |
| quiet | T01t pooled | 4 | 7.70% | 8.78% | -0.69 |
| quiet | T01t pooled | 16 | 7.62% | 8.37% | -0.78 |
| quiet | T01t pooled | 64 | 7.58% | 8.26% | -0.81 |
| quiet | BlockRun | 1 | 4.71% | 5.15% | +0.00 |
| quiet | BlockRun | 4 | 4.60% | 4.81% | -0.11 |
| quiet | BlockRun | 16 | 4.59% | 4.74% | -0.12 |
| quiet | BlockRun | 64 | 4.58% | 4.72% | -0.13 |
| quiet | StableEnrich(Out candidates excluded) | 1 | 6.82% | 8.48% | +0.00 |
| quiet | StableEnrich(Out candidates excluded) | 4 | 6.38% | 7.11% | -0.44 |
| quiet | StableEnrich(Out candidates excluded) | 16 | 6.33% | 6.84% | -0.50 |
| quiet | StableEnrich(Out candidates excluded) | 64 | 6.30% | 6.76% | -0.52 |

## 7. Table 4. per component share (main scenario, lower, mode N, V 1; revenue relative to)

| window | seller | N | verify | anchor | sampvrf | release | l1 | frozen | deduct | capital | total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | T01t median | 1 | 0.0084 | 0.1613 | 0.0501 | 0.0190 | 0.0008 | 0.0002 | 0.0017 | 0.0002 | 0.2418 |
| busy | T01t median | 64 | 0.0084 | 0.1533 | 0.0008 | 0.0161 | 0.0008 | 0.0002 | 0.0017 | 0.0002 | 0.1815 |
| busy | CoinStats(0.01 or less) | 1 | 0.0021 | 1.4601 | 0.7411 | 0.7153 | 0.0046 | 0.0000 | 0.0017 | 0.0872 | 3.0121 |
| busy | CoinStats(0.01 or less) | 64 | 0.0021 | 1.3400 | 0.0116 | 0.4526 | 0.0046 | 0.0000 | 0.0017 | 0.0872 | 1.8998 |
| busy | Exa(0.001 or less) | 1 | 0.0021 | 4.3041 | 2.5367 | 1.1832 | 0.0090 | 0.0000 | 0.0017 | 0.0246 | 8.0614 |
| busy | Exa(0.001 or less) | 64 | 0.0021 | 3.8932 | 0.0396 | 0.7450 | 0.0090 | 0.0000 | 0.0017 | 0.0246 | 4.7153 |
| busy | StableApify | 1 | 0.0021 | 0.1005 | 0.0449 | 0.0450 | 0.0004 | 0.0000 | 0.0017 | 0.0019 | 0.1966 |
| busy | StableApify | 64 | 0.0021 | 0.0932 | 0.0007 | 0.0291 | 0.0004 | 0.0000 | 0.0017 | 0.0019 | 0.1292 |
| median | T01t median | 1 | 0.0021 | 0.2281 | 0.1204 | 0.1150 | 0.0007 | 0.0000 | 0.0017 | 0.0064 | 0.4745 |
| median | T01t median | 64 | 0.0021 | 0.2086 | 0.0019 | 0.0723 | 0.0007 | 0.0000 | 0.0017 | 0.0064 | 0.2937 |
| median | CoinStats(0.01 or less) | 1 | 0.0021 | 2.3115 | 1.2010 | 1.1518 | 0.0070 | 0.0000 | 0.0017 | 0.2055 | 4.8807 |
| median | CoinStats(0.01 or less) | 64 | 0.0021 | 2.1170 | 0.0188 | 0.7260 | 0.0070 | 0.0000 | 0.0017 | 0.2055 | 3.0781 |
| median | Exa(0.001 or less) | 1 | 0.0021 | 4.2776 | 2.5190 | 1.0498 | 0.0089 | 0.0000 | 0.0017 | 0.0216 | 7.8807 |
| median | Exa(0.001 or less) | 64 | 0.0021 | 3.8696 | 0.0394 | 0.6642 | 0.0089 | 0.0000 | 0.0017 | 0.0216 | 4.6074 |
| median | StableApify | 1 | 0.0021 | 0.2419 | 0.1321 | 0.1250 | 0.0007 | 0.0000 | 0.0017 | 0.0092 | 0.5128 |
| median | StableApify | 64 | 0.0021 | 0.2205 | 0.0021 | 0.0782 | 0.0007 | 0.0000 | 0.0017 | 0.0092 | 0.3145 |
| quiet | T01t median | 1 | 0.0021 | 0.3431 | 0.1937 | 0.1818 | 0.0009 | 0.0000 | 0.0017 | 0.0108 | 0.7340 |
| quiet | T01t median | 64 | 0.0021 | 0.3117 | 0.0030 | 0.1131 | 0.0009 | 0.0000 | 0.0017 | 0.0108 | 0.4433 |
| quiet | CoinStats(0.01 or less) | 1 | 0.0021 | 1.7637 | 0.8338 | 0.8211 | 0.0062 | 0.0000 | 0.0017 | 0.3736 | 3.8022 |
| quiet | CoinStats(0.01 or less) | 64 | 0.0021 | 1.6287 | 0.0130 | 0.5255 | 0.0062 | 0.0000 | 0.0017 | 0.3736 | 2.5509 |
| quiet | Exa(0.001 or less) | 1 | 0.0021 | 5.0804 | 3.0571 | 1.1220 | 0.0097 | 0.0000 | 0.0017 | 0.0232 | 9.2962 |
| quiet | Exa(0.001 or less) | 64 | 0.0021 | 4.5852 | 0.0478 | 0.7079 | 0.0097 | 0.0000 | 0.0017 | 0.0232 | 5.3776 |
| quiet | StableApify | 1 | 0.0021 | 0.3414 | 0.1911 | 0.1797 | 0.0009 | 0.0000 | 0.0017 | 0.0171 | 0.7340 |
| quiet | StableApify | 64 | 0.0021 | 0.3104 | 0.0030 | 0.1120 | 0.0009 | 0.0000 | 0.0017 | 0.0171 | 0.4472 |

("T01t median" row seller total middle two seller component is the mean.)

## 8. Table 6. scenario comparison (mode N, V 1): median seller(lower / upper) and 10% within seller count(lower / upper)

| scenario | N | busy median | median median | quiet median | 10% within count(busy, median, quiet; lower) | 10% within count(upper) |
|---|---|---|---|---|---|---|
| main | 1 | 24.18% / 37.80% | 47.45% / 70.92% | 73.40% / 111.34% | 1, 1, 2 | 1, 1, 2 |
| main | 4 | 19.61% / 24.86% | 33.75% / 39.85% | 51.37% / 61.37% | 1, 1, 2 | 1, 1, 2 |
| main | 16 | 18.44% / 21.59% | 30.25% / 32.01% | 45.74% / 48.75% | 1, 1, 2 | 1, 1, 2 |
| main | 64 | 18.15% / 20.79% | 29.37% / 30.04% | 44.33% / 45.60% | 1, 1, 2 | 1, 1, 2 |
| measured | 1 | 24.18% / 37.80% | 47.45% / 70.92% | 73.40% / 111.34% | 1, 1, 2 | 1, 1, 2 |
| measured | 4 | 19.92% / 25.13% | 34.39% / 40.49% | 52.40% / 62.40% | 1, 1, 2 | 1, 1, 2 |
| measured | 16 | 19.39% / 22.58% | 32.63% / 34.39% | 49.57% / 52.58% | 1, 1, 2 | 1, 1, 2 |
| measured | 64 | 19.15% / 21.90% | 32.06% / 32.74% | 48.66% / 49.93% | 1, 1, 2 | 1, 1, 2 |
| S,P2 | 1 | 24.18% / 37.80% | 47.45% / 70.92% | 73.40% / 111.34% | 1, 1, 2 | 1, 1, 2 |
| S,P2 | 4 | 22.05% / 31.96% | 45.46% / 70.38% | 69.77% / 110.07% | 1, 1, 2 | 1, 1, 2 |
| S,P2 | 16 | 19.69% / 26.21% | 42.78% / 67.26% | 65.38% / 103.81% | 1, 1, 2 | 1, 1, 2 |
| S,P2 | 64 | 18.60% / 22.74% | 39.02% / 57.86% | 58.81% / 87.27% | 1, 1, 2 | 1, 1, 2 |
| Z | 1 | 21.57% / 35.18% | 41.17% / 64.65% | 63.31% / 101.25% | 1, 1, 2 | 1, 1, 2 |
| Z | 4 | 17.00% / 22.25% | 27.48% / 33.58% | 41.28% / 51.28% | 1, 1, 2 | 1, 1, 2 |
| Z | 16 | 15.83% / 18.98% | 24.01% / 26.56% | 35.65% / 38.67% | 1, 1, 2 | 1, 1, 2 |
| Z | 64 | 15.54% / 18.17% | 23.42% / 25.14% | 34.24% / 35.51% | 1, 1, 2 | 1, 1, 2 |
| main (limit) | 4096 | 18.08% / 20.55% | 29.15% / 29.46% | 43.97% / 44.66% | 1, 1, 2 | 1, 1, 2 |

small seller three lower cost(N 64 / limit 4096, main scenario and Z):

| window | seller | main N 1 | main N 64 | main N 4096 | Z N 1 | Z N 64 |
|---|---|---|---|---|---|---|
| busy | CoinStats(0.01 or less) | 301.21% | 189.98% | 188.61% | 262.61% | 151.38% |
| busy | Exa(0.001 or less) | 806.14% | 471.53% | 467.13% | 674.03% | 339.41% |
| busy | StableApify | 19.66% | 12.92% | 12.84% | 17.32% | 10.58% |
| median | CoinStats(0.01 or less) | 488.07% | 307.81% | 305.58% | 425.52% | 245.26% |
| median | Exa(0.001 or less) | 788.07% | 460.74% | 456.42% | 656.88% | 329.55% |
| median | StableApify | 51.28% | 31.45% | 31.21% | 44.40% | 24.58% |
| quiet | CoinStats(0.01 or less) | 380.22% | 255.09% | 253.56% | 336.80% | 211.66% |
| quiet | Exa(0.001 or less) | 929.62% | 537.76% | 532.53% | 770.40% | 378.54% |
| quiet | StableApify | 73.40% | 44.72% | 44.36% | 63.45% | 34.77% |

## 9. mode S, V 1, main scenario: median seller(lower / upper) and 10% within seller count(lower)

| N | busy | median | quiet | 10% within count(lower) |
|---|---|---|---|---|
| 1 | 30.97% / 41.90% | 47.57% / 71.05% | 73.52% / 111.46% | 0, 0, 0 |
| 4 | 27.43% / 31.66% | 33.88% / 39.98% | 51.49% / 61.49% | 0, 0, 0 |
| 16 | 26.89% / 29.08% | 30.66% / 32.13% | 45.86% / 48.88% | 0, 0, 0 |
| 64 | 26.81% / 28.43% | 30.16% / 30.75% | 44.45% / 45.72% | 0, 0, 0 |

## 10. check

- EIP-7623 lower bound run gas over cell: none
- transaction within unit count m_eff (main scenario, N 64, lower, chosen k): anchor / release
  - busy: StableEnrich 28 / 12, OneSource 20 / 49, CoinMarketCap 60 / 64, StableApify 58 / 64, Exa 64 / 64, CoinStats 64 / 64; BlockRun 1 / 1
  - median: StableEnrich 33 / 15, OneSource 26 / 20, CoinMarketCap 64 / 64, StableApify 64 / 64, Exa 64 / 64, CoinStats 64 / 64; BlockRun 1 / 1
  - quiet: StableEnrich 25 / 13, OneSource 32 / 35, CoinMarketCap 64 / 64, StableApify 64 / 64, Exa 64 / 64, CoinStats 62 / 64; BlockRun 24 / 12
- chosen k (main scenario, lower): N 1 vs N 64
  - busy: StableEnrich 32 vs 32, OneSource 32 vs 32, CoinMarketCap 32 vs 32, StableApify 1 vs 1, Exa 32 vs 32, CoinStats 1 vs 1
  - median: StableEnrich 32 vs 32, OneSource 32 vs 32, CoinMarketCap 1 vs 1, StableApify 1 vs 1, Exa 32 vs 32, CoinStats 1 vs 1
  - quiet: StableEnrich 32 vs 32, OneSource 32 vs 32, CoinMarketCap 1 vs 1, StableApify 1 vs 1, Exa 32 vs 32, CoinStats 1 vs 1
- N = 1 main, measured, S,P2 scenario median K11b and equal(1e-15 within): check

## 11. by hand again cell three cell (main scenario, mode N, V 1, lower)

constant: 1 gas = 0.010 gwei = 2.4014e-08 USD, 1 L1 wei = 2.4014e-15 USD. anchor run gas(signature) = 189907.00 + 21649.375 x, x = n / A_p (EIP-7623 lower bound not reach not). bundle anchor unit gas = run gas − 21,000 + 24,252 / m (P1). ECVRF sample = (gusd(48,669 + 78,301) + wusd(734,567,965 + 2,593,604,493)) / N. release gas = Ru × 114,624 × (0.6 + 0.4 / m) + 2,930 n + 2,083 n_s. remaining component(verify, l1, frozen, deduct, capital) K11b appendix and same formula.

### quiet, Exa(0.001 or less), N 64 (N 1: 929.62%)

- input: R = 0.178000 USDC, n = 178, n_s = 0.178000, days 15, k = 32, E_p = 178, A_p = 178, x = 1.0000, Ru = 68, anchor unit gas(self submission) = 211556.4, m_anchor = 64, m_release = 64.
- bundle anchor unit gas = 190935.3 (= 211556.4 − 21,000 + 24,252 / 64)
- component(revenue relative to) N 64: verify 0.002090, anchor 4.585197, sampvrf 0.047767, release 0.707924, l1 0.009712; N 1: verify 0.002090, anchor 5.080399, sampvrf 3.057101, release 1.121977, l1 0.009712
- frozen 0.000001, deduct 0.001730, capital 0.023172, total 5.377594 (= 537.76%)

### busy, StableApify, N 4 (N 1: 19.66%)

- input: R = 2.995000 USDC, n = 193, n_s = 2.995000, days 21, k = 1, E_p = 44, A_p = 44, x = 4.3864, Ru = 44, anchor unit gas(self submission) = 284869.0, m_anchor = 4, m_release = 4.
- bundle anchor unit gas = 269932.0 (= 284869.0 − 21,000 + 24,252 / 4)
- component(revenue relative to) N 4: verify 0.002090, anchor 0.095232, sampvrf 0.011228, release 0.032892, l1 0.000380; N 1: verify 0.002090, anchor 0.100502, sampvrf 0.044912, release 0.045023, l1 0.000380
- frozen 0.000013, deduct 0.001730, capital 0.001947, total 0.145511 (= 14.55%)

### median, CoinStats(0.01 or less), N 16 (N 1: 488.07%)

- input: R = 0.028000 USDC, n = 28, n_s = 0.028000, days 21, k = 1, E_p = 11, A_p = 11, x = 2.5455, Ru = 11, anchor unit gas(self submission) = 245014.5, m_anchor = 16, m_release = 16.
- bundle anchor unit gas = 225530.2 (= 245014.5 − 21,000 + 24,252 / 16)
- component(revenue relative to) N 16: verify 0.002090, anchor 2.127704, sampvrf 0.075063, release 0.746280, l1 0.007010; N 1: verify 0.002090, anchor 2.311523, sampvrf 1.201004, release 1.151801, l1 0.007010
- frozen 0.000000, deduct 0.001730, capital 0.205505, total 3.165382 (= 316.54%)

