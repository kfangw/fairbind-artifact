# K11b output (k11b.py)

K11b_settings.md SHA-256 absent. settings this run before were fixed(K11b_results.md same value recorded).

| input | SHA-256 prior 8 |
|---|---|
| docs/05_run-evidence/R7R8/out/R9/R9-5/price_cache.json | ec267a05 |
| docs/11_journal/F/data-review/target_sellers_all_summary.csv | 03cbc0f0 |
| docs/11_journal/F/data-review/target_sellers_values.csv | d7127938 |
| docs/05_run-evidence/design2/median-period/seed0/base_v1_auto-zero-reject/condition-01-seed-0/addresses_observed.csv | eeec2035 |
| docs/05_run-evidence/design2/median-period/seed0/base_v0.2_auto-zero-reject/condition-01-seed-0/addresses_observed.csv | 5c1c8a44 |
| docs/11_journal/F/I4_loss-reimpl/d3_members.json | 4c771a52 |
| data/processed/agg_2026-10-21/epochs_median.csv.gz | b8f1ecaf |
| data/processed/agg_2026-10-21/epochs_busy.csv.gz | 0a4da864 |
| docs/11_journal/G10_gas/logs_b/g10b_l1fee.tsv.gz | cff335ad |
| docs/11_journal/G10_gas/logs_c/g10c_l1fee.tsv.gz | aea1ab19 |
| docs/11_journal/G10_gas/logs_c/g10c_summary.tsv.gz | a57a43a8 |
| docs/11_journal/G10_gas/logs_c/g10c_l1fee_big.tsv.gz | fa7f799d |
| docs/11_journal/G10_gas/logs_d/g10d_vrf.tsv.gz | c78595bc |
| docs/11_journal/G10_gas/G10d_gas.md | absent |
| docs/11_journal/G11_gas/logs/p5_l1fee.tsv.gz | 19b8abff |
| docs/11_journal/G11_gas/G11_gas.md | absent |
| docs/11_journal/K11/k11_output.md | bf8389b2 |
| docs/11_journal/K11/k11.py | absent |
| docs/11_journal/rule10-candidate/F1_seller-stage-classes.csv | absent |
| docs/11_journal/K_revision-cost/K10/k10h.py | absent |
| docs/11_journal/K_revision-cost/K10/k10h_output.md | absent |

R10 list: none. per epoch sales count epochs_{busy,median}.csv.gz(600 s epoch), partial seller E1 k10h_output.md 2 (sec.) value busy StableEnrich 2046, busy Exa 195, busy CoinStats 16, median StableEnrich 2178, median Exa 220, median CoinStats 11.

## 1. K11 reproduction: old gas(set_gas("old")) put in this file k11_output.md cells as is outputs

| Table | cell count | equal |
|---|---|---|
| 4 (sec.) seller row(N, S: k, lower, upper, lower carry-over) | 42 | 42 |
| 4 (sec.) set row(N, S, S-d, S-120) | 240 | 240 |
| 5 (sec.) V grid | 70 | 70 |

old gas k11_output.md 352cell among 352cells as is outputs.

## 2. changed gas constant (old value K11, new value K11b)

| constant | old value | new value | new value / old value |
|---|---|---|---|
| anchor per sale gas, signature | 15,668 | 21,649.4 | 1.382 |
| anchor fixed gas, signature | 148,812 | 189,907 | 1.276 |
| EIP-7623 lower slope, signature | 13,562.5 | 13,731.2 | 1.012 |
| EIP-7623 lower intercept, signature | 28,120 | 34,460 | 1.225 |
| anchor per sale gas, signature none | 9,004 | 12,953.3 | 1.439 |
| anchor fixed gas, signature none | 129,299 | 190,538.3 | 1.474 |
| EIP-7623 lower slope, signature none | 10,630 | 10,790 | 1.015 |
| EIP-7623 lower intercept, signature none | 28,120 | 34,470 | 1.226 |
| sample request ECVRF (G_REQ) | 51,550 | 48,669 | 0.944 |
| sample value accepted ECVRF (G_VRF_EXP) | 80,900 | 78,301 | 0.968 |
| sample request Chainlink (CL_REQ) | 96,000 | 119,160 | 1.241 |
| proof call tier 1a (RS3 cell) | 55,556 | 86,824 | 1.563 |
| proof call tier 0 | 552,125 | 604,522 | 1.095 |
| proof call tier 0 upper (SP0_UP) | 672,029 | 724,426 | 1.078 |
| dispute open (G_OPEN) | 122,222 | 166,809 | 1.365 |
| decryption dispute 4 KB (G_DEC) | 186,500 | 187,750 | 1.007 |

not changing not one: bundled release and direct release(REL_F 114,624, REL_M 2,930, REL_K 2,083), proof call tier 1b(TEE 36,440), settlement gas, failure path 104,276, Chainlink fulfillment 157,644, transaction capacity CAP_GAS {1: 924, 0: 1564}, L1 wei all, upper margin 5,200 + per level 900.


## 3. mode parameters and retention, freeze interval (block, 2 s)

| mode | b | a_A | τ_V + 1 + T_V | T_p | T_c | H(1) | H(32) | Δ_f | H(1) time | Δ_f time | OneSource proof |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OLD | bond(V) = V/0.675 | 20 | 31 | 1,800 | 1,800 | 3,951 | 13,251 | 2,151 | 2.19 | 1.20 | SP0 |
| N | V | 120 | 31 | 1,800 | 1,800 | 4,051 | 13,351 | 2,251 | 2.25 | 1.25 | SP0 |
| S | V | 90,600 | 22,651 | 24,420 | 24,420 | 162,391 | 171,691 | 137,971 | 90.22 | 76.65 | RS3(signature feed kept) |
| S-d | V | 45,300 | 22,651 | 24,420 | 24,420 | 117,091 | 126,391 | 92,671 | 65.05 | 51.48 | RS3(signature feed kept) |
| S-120 | V | 120 | 22,651 | 24,420 | 24,420 | 71,911 | 81,211 | 47,491 | 39.95 | 26.38 | SP0 |

## 4. admission inspection (19) and related inspection (value: left side vs right side)

| inspection | N | S | S-d | S-120 |
|---|---|---|---|---|
| (19) m_a ≥ d_inc | 30 ≥ 30: holds | 22,650 ≥ 22,650: holds | 22,650 ≥ 22,650: holds | 30 ≥ 22,650: does not hold not |
| (19) a_A ≥ d_inc + m_a (registration when) | 120 ≥ 60: holds | 90,600 ≥ 45,300: holds | 45,300 ≥ 45,300: holds | 120 ≥ 22,680: does not hold not |
| (19) a_F ≥ d_inc + m_a (joining when) | 60 ≥ 60: holds | 45,300 ≥ 45,300: holds | set none(applicable none): - | 60 ≥ 22,680: does not hold not |
| (19) a_A − a_F ≥ d_inc + m_a (joining when) | 60 ≥ 60: holds | 45,300 ≥ 45,300: holds | set none(applicable none): - | 60 ≥ 22,680: does not hold not |
| (19) 100 ≤ a_A ≤ 150 | 120: holds | 90,600: does not hold not | 45,300: does not hold not | 120: holds |
| (1) T_epoch ≥ τ_V + 1 + T_V | 300 ≥ 31: holds | 300 ≥ 22,651: does not hold not | 300 ≥ 22,651: does not hold not | 300 ≥ 22,651: does not hold not |
| (1) a_A < T_epoch | 120 < 300: holds | 90,600 < 300: does not hold not | 45,300 < 300: does not hold not | 120 < 300: holds |
| (3) w_b ≥ 1 + d_inc | 1,800 ≥ 31: holds | 22,651 ≥ 22,651: holds | 22,651 ≥ 22,651: holds | 22,651 ≥ 22,651: holds |
| (5) tier 0: 300 + a_A ≤ 8,191 − margin(8,000) | 420 ≤ 8,000: holds | 90,900 ≤ 8,000: does not hold not | 45,600 ≤ 8,000: does not hold not | 420 ≤ 8,000: holds |
| (11) T_rs ≤ T_c − d_inc | 1,770 ≤ 1,770: holds | 1,770 ≤ 1,770: holds | 1,770 ≤ 1,770: holds | 1,770 ≤ 1,770: holds |
| (15) T_x ≥ d_inc | 30 ≥ 30: holds | 22,650 ≥ 22,650: holds | 22,650 ≥ 22,650: holds | 22,650 ≥ 22,650: holds |
| (16) tier 1a: 2 × a_A seconds ≥ δ_sig + update spacing | left side 240 s(right side value none): - | left side 181,200 s(right side value none): - | left side 90,600 s(right side value none): - | left side 240 s(right side value none): - |

verdict 1 (19):
- N: pass
- S: inequality holds, range fails
- S-d: inequality holds, range fails
- S-120: fails(m_a ≥ d_inc, a_A ≥ d_inc + m_a (registration when), a_F ≥ d_inc + m_a (joining when), a_A − a_F ≥ d_inc + m_a (joining when))

## 5. per seller and set total (K11b; revenue relative to %; σ 1, w 0.00173, r 10%, a 0, per seller optimal k)

| window | V | seller | R USDC | n | N k | N lower | N upper | N lower carry-over | S k | S lower | S upper | S lower carry-over |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | 0.2 | StableEnrich(Out candidates excluded) | 1458.90 | 38369 | 32 | 6.89% | 8.25% | 10.83% | 32 | 88.66% | 90.02% | 92.61% |
| busy | 0.2 | OneSource | 30.91 | 7194 | 32 | 28.61% | 36.50% | 63.35% | 32 | 26.32% | 32.77% | 61.06% |
| busy | 0.2 | CoinMarketCap | 43.62 | 4362 | 32 | 26.61% | 47.38% | 42.39% | 32 | 32.19% | 52.97% | 47.98% |
| busy | 0.2 | StableApify | 3.00 | 193 | 1 | 20.37% | 29.26% | 30.49% | 1 | 20.85% | 29.75% | 30.98% |
| busy | 0.2 | Exa(0.001 or less) | 0.23 | 235 | 32 | 805.04% | 1411.42% | 986.86% | 32 | 805.17% | 1411.55% | 986.99% |
| busy | 0.2 | CoinStats(0.01 or less) | 0.07 | 45 | 1 | 295.09% | 441.61% | 405.80% | 1 | 295.20% | 441.72% | 405.91% |
| busy | 0.2 | BlockRun | 105338.04 | 9656870 | 4 | 95.13% | 95.32% | 108.68% | 4 | 106.24% | 106.43% | 119.79% |
| busy | 1 | StableEnrich(Out candidates excluded) | 1458.90 | 38369 | 32 | 3.67% | 4.89% | 7.62% | 32 | 35.02% | 36.25% | 38.97% |
| busy | 1 | OneSource | 30.91 | 7194 | 32 | 22.67% | 29.27% | 57.41% | 32 | 22.30% | 28.62% | 57.04% |
| busy | 1 | CoinMarketCap | 43.62 | 4362 | 32 | 25.69% | 46.32% | 41.47% | 32 | 26.91% | 47.55% | 42.70% |
| busy | 1 | StableApify | 3.00 | 193 | 1 | 19.66% | 28.42% | 29.79% | 1 | 19.84% | 28.59% | 29.96% |
| busy | 1 | Exa(0.001 or less) | 0.23 | 235 | 32 | 806.14% | 1412.38% | 987.96% | 32 | 806.25% | 1412.49% | 988.07% |
| busy | 1 | CoinStats(0.01 or less) | 0.07 | 45 | 1 | 301.21% | 447.59% | 411.92% | 1 | 301.31% | 447.69% | 412.02% |
| busy | 1 | BlockRun | 105338.04 | 9656870 | 4 | 42.05% | 42.10% | 55.60% | 4 | 105.89% | 105.94% | 119.44% |
| median | 0.2 | StableEnrich(Out candidates excluded) | 1134.66 | 31237 | 32 | 6.39% | 8.17% | 10.54% | 32 | 77.94% | 79.72% | 82.09% |
| median | 0.2 | OneSource | 81.22 | 22909 | 32 | 35.61% | 49.11% | 77.88% | 32 | 39.36% | 51.43% | 81.63% |
| median | 0.2 | CoinMarketCap | 1.63 | 163 | 1 | 44.19% | 65.44% | 60.43% | 1 | 44.50% | 65.75% | 60.74% |
| median | 0.2 | StableApify | 0.62 | 54 | 1 | 51.40% | 77.37% | 65.94% | 1 | 51.58% | 77.55% | 66.12% |
| median | 0.2 | Exa(0.001 or less) | 0.27 | 267 | 32 | 787.20% | 1401.78% | 968.78% | 32 | 787.34% | 1401.91% | 968.91% |
| median | 0.2 | CoinStats(0.01 or less) | 0.03 | 28 | 1 | 472.48% | 712.60% | 636.38% | 1 | 472.59% | 712.70% | 636.49% |
| median | 0.2 | BlockRun | 127900.66 | 3319274 | 4 | 78.11% | 78.22% | 81.95% | 4 | 102.01% | 102.12% | 105.84% |
| median | 1 | StableEnrich(Out candidates excluded) | 1134.66 | 31237 | 32 | 4.00% | 5.67% | 8.15% | 32 | 29.43% | 31.09% | 33.58% |
| median | 1 | OneSource | 81.22 | 22909 | 32 | 29.57% | 41.79% | 71.84% | 32 | 30.49% | 42.42% | 72.76% |
| median | 1 | CoinMarketCap | 1.63 | 163 | 1 | 43.61% | 64.72% | 59.85% | 1 | 43.76% | 64.87% | 59.99% |
| median | 1 | StableApify | 0.62 | 54 | 1 | 51.28% | 77.11% | 65.82% | 1 | 51.39% | 77.23% | 65.93% |
| median | 1 | Exa(0.001 or less) | 0.27 | 267 | 32 | 788.07% | 1402.50% | 969.65% | 32 | 788.18% | 1402.61% | 969.75% |
| median | 1 | CoinStats(0.01 or less) | 0.03 | 28 | 1 | 488.07% | 728.04% | 651.97% | 1 | 488.17% | 728.14% | 652.07% |
| median | 1 | BlockRun | 127900.66 | 3319274 | 4 | 33.60% | 33.64% | 37.44% | 4 | 101.86% | 101.90% | 105.70% |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | 726.43 | 27866 | 32 | 6.82% | 8.48% | 12.57% | 32 | 75.81% | 77.46% | 81.55% |
| quiet | 0.2 | OneSource | 50.28 | 8329 | 32 | 26.17% | 36.73% | 51.09% | 32 | 28.65% | 37.78% | 53.58% |
| quiet | 0.2 | CoinMarketCap | 0.95 | 95 | 1 | 73.91% | 112.10% | 91.32% | 1 | 74.18% | 112.38% | 91.60% |
| quiet | 0.2 | StableApify | 0.24 | 26 | 1 | 72.89% | 110.85% | 91.46% | 1 | 73.03% | 111.00% | 91.60% |
| quiet | 0.2 | Exa(0.001 or less) | 0.18 | 178 | 32 | 928.63% | 1688.45% | 1117.42% | 32 | 928.76% | 1688.58% | 1117.55% |
| quiet | 0.2 | CoinStats(0.01 or less) | 0.01 | 11 | 1 | 351.19% | 534.49% | 510.16% | 1 | 351.29% | 534.59% | 510.26% |
| quiet | 0.2 | BlockRun | 2836.67 | 28710 | 32 | 4.71% | 5.15% | 6.23% | 32 | 90.00% | 90.44% | 91.51% |
| quiet | 1 | StableEnrich(Out candidates excluded) | 726.43 | 27866 | 32 | 4.51% | 6.04% | 10.25% | 32 | 27.65% | 29.18% | 33.39% |
| quiet | 1 | OneSource | 50.28 | 8329 | 32 | 20.15% | 29.42% | 45.08% | 32 | 20.79% | 29.78% | 45.72% |
| quiet | 1 | CoinMarketCap | 0.95 | 95 | 1 | 73.40% | 111.45% | 90.81% | 1 | 73.53% | 111.59% | 90.95% |
| quiet | 1 | StableApify | 0.24 | 26 | 1 | 73.40% | 111.23% | 91.97% | 1 | 73.51% | 111.34% | 92.08% |
| quiet | 1 | Exa(0.001 or less) | 0.18 | 178 | 32 | 929.62% | 1689.30% | 1118.41% | 32 | 929.73% | 1689.41% | 1118.52% |
| quiet | 1 | CoinStats(0.01 or less) | 0.01 | 11 | 1 | 380.22% | 563.38% | 539.19% | 1 | 380.32% | 563.48% | 539.29% |
| quiet | 1 | BlockRun | 2836.67 | 28710 | 32 | 2.70% | 3.10% | 4.21% | 32 | 61.91% | 62.31% | 63.43% |

set pooled / median (lower; upper; lower carry-over):

| set | V | mode | lower pooled / median | upper pooled / median | lower carry-over pooled / median |
|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | N | 8.05% / 27.61% | 10.20% / 41.94% | 12.99% / 52.87% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S | 85.79% / 60.43% | 87.91% / 71.49% | 90.73% / 76.83% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S-d | 73.30% / 52.98% | 75.43% / 64.04% | 78.25% / 69.64% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S-120 | 50.48% / 40.73% | 52.63% / 51.07% | 55.42% / 60.08% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | N | 4.84% / 24.18% | 6.84% / 37.80% | 9.79% / 49.44% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S | 34.64% / 30.97% | 36.63% / 41.90% | 39.58% / 49.87% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S-d | 25.91% / 26.18% | 27.89% / 37.84% | 30.85% / 49.52% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S-120 | 16.06% / 24.54% | 18.06% / 38.16% | 21.00% / 49.80% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | N | 8.59% / 47.79% | 11.34% / 71.41% | 15.35% / 71.91% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S | 75.48% / 64.76% | 78.12% / 78.64% | 82.23% / 81.86% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S-d | 61.75% / 57.48% | 64.39% / 71.57% | 68.50% / 72.99% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S-120 | 41.11% / 47.89% | 43.85% / 71.50% | 47.86% / 73.68% |
| classified data seller tier 0/1 endpoint revenue median | 1 | N | 5.97% / 47.45% | 8.51% / 70.92% | 12.72% / 68.83% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S | 29.71% / 47.57% | 32.23% / 71.05% | 36.46% / 69.35% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S-d | 22.52% / 47.54% | 25.04% / 71.01% | 29.27% / 68.97% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S-120 | 14.70% / 47.50% | 17.25% / 70.97% | 21.45% / 69.22% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | N | 8.39% / 73.40% | 10.85% / 111.48% | 15.43% / 91.39% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S | 72.96% / 75.00% | 75.33% / 111.69% | 80.00% / 91.60% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S-d | 59.17% / 73.54% | 61.54% / 111.62% | 66.21% / 91.54% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S-120 | 39.07% / 73.48% | 41.53% / 111.56% | 46.11% / 91.47% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | N | 5.84% / 73.40% | 8.10% / 111.34% | 12.88% / 91.39% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S | 27.49% / 73.52% | 29.73% / 111.46% | 34.53% / 91.51% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S-d | 20.86% / 73.49% | 23.10% / 111.43% | 27.90% / 91.48% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S-120 | 13.73% / 73.45% | 15.99% / 111.39% | 20.77% / 91.44% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | N | 27.23% / 26.61% | 43.74% / 47.38% | 50.91% / 57.04% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S | 31.98% / 32.19% | 48.48% / 52.97% | 55.66% / 61.06% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S-d | 30.43% / 30.37% | 46.93% / 51.14% | 54.10% / 59.74% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S-120 | 28.85% / 28.51% | 45.36% / 49.29% | 52.53% / 58.40% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | N | 26.35% / 25.69% | 42.71% / 46.32% | 50.02% / 56.14% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S | 27.39% / 26.91% | 43.76% / 47.55% | 51.07% / 57.04% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S-d | 27.05% / 26.51% | 43.42% / 47.14% | 50.73% / 56.75% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S-120 | 26.71% / 26.11% | 43.07% / 46.74% | 50.38% / 56.45% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | N | 32.32% / 51.40% | 46.66% / 77.37% | 74.36% / 71.57% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S | 42.08% / 51.58% | 56.42% / 77.55% | 84.12% / 81.63% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S-d | 38.94% / 51.52% | 53.28% / 77.50% | 80.98% / 78.39% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S-120 | 35.70% / 51.47% | 50.04% / 77.44% | 77.73% / 75.05% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | N | 31.36% / 51.28% | 45.56% / 77.11% | 73.39% / 70.58% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S | 33.47% / 51.39% | 47.68% / 77.23% | 75.51% / 72.76% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S-d | 32.78% / 51.36% | 46.98% / 77.20% | 74.81% / 72.04% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S-120 | 32.08% / 51.32% | 46.28% / 77.16% | 74.11% / 71.32% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | N | 24.30% / 73.91% | 36.72% / 112.10% | 49.65% / 91.46% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S | 32.87% / 74.18% | 45.28% / 112.38% | 58.22% / 91.60% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S-d | 30.10% / 74.10% | 42.51% / 112.29% | 55.45% / 91.56% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S-120 | 27.25% / 74.01% | 39.67% / 112.20% | 52.60% / 91.52% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | N | 23.36% / 73.40% | 35.64% / 111.45% | 48.71% / 91.97% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S | 25.22% / 73.53% | 37.50% / 111.59% | 50.57% / 92.08% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S-d | 24.61% / 73.49% | 36.88% / 111.55% | 49.96% / 92.05% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S-120 | 23.99% / 73.45% | 36.27% / 111.51% | 49.34% / 92.02% |
| D94 | 0.2 | N | 8.38% / 36.80% | 8.65% / 60.19% | 9.73% / 57.16% |
| D94 | 0.2 | S | 95.00% / 48.31% | 95.27% / 77.27% | 96.35% / 73.02% |
| D94 | 0.2 | S-d | 91.24% / 47.95% | 91.50% / 75.31% | 92.59% / 66.57% |
| D94 | 0.2 | S-120 | 77.17% / 44.94% | 77.44% / 70.99% | 78.53% / 63.26% |
| D94 | 1 | N | 7.95% / 35.95% | 8.21% / 59.52% | 9.30% / 56.35% |
| D94 | 1 | S | 92.47% / 44.09% | 92.73% / 70.12% | 93.83% / 63.73% |
| D94 | 1 | S-d | 88.46% / 43.98% | 88.72% / 70.05% | 89.81% / 63.68% |
| D94 | 1 | S-120 | 74.21% / 43.22% | 74.47% / 65.02% | 75.56% / 60.86% |
| K10 data(comparison) busy | 0.2 | N | 7.73% / 21.33% | 10.24% / 29.01% | 12.43% / 36.44% |
| K10 data(comparison) busy | 0.2 | S | 75.84% / 29.25% | 78.35% / 44.27% | 80.53% / 54.52% |
| K10 data(comparison) busy | 0.2 | S-d | 64.82% / 27.68% | 67.33% / 42.17% | 69.52% / 52.95% |
| K10 data(comparison) busy | 0.2 | S-120 | 44.73% / 26.09% | 47.24% / 40.03% | 49.42% / 49.85% |
| K10 data(comparison) busy | 1 | N | 5.03% / 20.53% | 7.42% / 28.07% | 9.72% / 35.63% |
| K10 data(comparison) busy | 1 | S | 31.46% / 24.61% | 33.85% / 32.58% | 36.15% / 40.89% |
| K10 data(comparison) busy | 1 | S-d | 23.71% / 23.98% | 26.10% / 28.43% | 28.41% / 36.10% |
| K10 data(comparison) busy | 1 | S-120 | 14.96% / 20.72% | 17.35% / 28.26% | 19.66% / 35.87% |
| K10 data(comparison) median | 0.2 | N | 6.36% / 29.30% | 8.73% / 41.37% | 11.33% / 60.43% |
| K10 data(comparison) median | 0.2 | S | 52.78% / 44.50% | 55.15% / 65.75% | 57.75% / 66.12% |
| K10 data(comparison) median | 0.2 | S-d | 43.07% / 44.40% | 45.44% / 65.21% | 48.04% / 66.06% |
| K10 data(comparison) median | 0.2 | S-120 | 28.50% / 41.06% | 30.87% / 44.85% | 33.48% / 60.54% |
| K10 data(comparison) median | 1 | N | 4.79% / 28.31% | 7.07% / 40.24% | 9.76% / 59.85% |
| K10 data(comparison) median | 1 | S | 21.81% / 30.49% | 24.08% / 42.42% | 26.78% / 59.99% |
| K10 data(comparison) median | 1 | S-d | 16.64% / 29.78% | 18.91% / 41.70% | 21.61% / 59.95% |
| K10 data(comparison) median | 1 | S-120 | 10.99% / 29.05% | 13.27% / 40.98% | 15.97% / 59.91% |
| K10 data(comparison) quiet | 0.2 | N | 6.07% / 19.86% | 8.13% / 28.98% | 11.13% / 44.78% |
| K10 data(comparison) quiet | 0.2 | S | 50.31% / 47.22% | 52.37% / 77.46% | 55.37% / 72.75% |
| K10 data(comparison) quiet | 0.2 | S-d | 40.74% / 46.68% | 42.80% / 62.89% | 45.80% / 66.98% |
| K10 data(comparison) quiet | 0.2 | S-120 | 26.74% / 39.47% | 28.81% / 41.13% | 31.80% / 47.81% |
| K10 data(comparison) quiet | 1 | N | 4.54% / 18.89% | 6.51% / 27.87% | 9.60% / 43.81% |
| K10 data(comparison) quiet | 1 | S | 19.88% / 27.65% | 21.85% / 29.78% | 24.94% / 45.72% |
| K10 data(comparison) quiet | 1 | S-d | 15.18% / 20.59% | 17.14% / 29.15% | 20.24% / 45.09% |
| K10 data(comparison) quiet | 1 | S-120 | 10.09% / 19.54% | 12.05% / 28.52% | 15.15% / 44.46% |

S OneSource without T01t(sensitivity; lower pooled / median):

| window | V | S lower | S upper | N lower(same set) |
|---|---|---|---|---|
| busy | 0.2 | 87.01% / 88.66% | 89.05% / 90.02% | 7.62% / 26.61% |
| busy | 1 | 34.89% / 35.02% | 36.79% / 47.55% | 4.48% / 25.69% |
| median | 0.2 | 78.05% / 77.94% | 80.03% / 79.72% | 6.66% / 51.40% |
| median | 1 | 29.65% / 51.39% | 31.51% / 77.23% | 4.28% / 51.28% |
| quiet | 0.2 | 76.02% / 75.81% | 77.92% / 112.38% | 7.16% / 73.91% |
| quiet | 1 | 27.95% / 73.53% | 29.73% / 111.59% | 4.85% / 73.40% |

## 6. V grid set total (lower pooled / median; upper pooled / median)

| set | mode | V 0.2 | V 0.5 | V 1 | V 2 | V 5 |
|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | N | 8.05% / 27.61%; 10.20% / 41.94% | 5.67% / 25.03%; 7.71% / 38.83% | 4.84% / 24.18%; 6.84% / 37.80% | 4.43% / 23.76%; 6.41% / 37.34% | 4.19% / 23.55%; 6.15% / 37.57% |
| classified data seller tier 0/1 endpoint revenue busy | S | 85.79% / 60.43%; 87.91% / 71.49% | 55.51% / 42.60%; 57.54% / 53.56% | 34.64% / 30.97%; 36.63% / 41.90% | 20.82% / 24.03%; 22.80% / 37.74% | 11.19% / 23.72%; 13.15% / 37.79% |
| classified data seller tier 0/1 endpoint revenue median | N | 8.59% / 47.79%; 11.34% / 71.41% | 6.72% / 47.34%; 9.32% / 70.85% | 5.97% / 47.45%; 8.51% / 70.92% | 5.60% / 47.97%; 8.11% / 71.43% | 5.38% / 49.82%; 7.88% / 73.27% |
| classified data seller tier 0/1 endpoint revenue median | S | 75.48% / 64.76%; 78.12% / 78.64% | 47.89% / 49.98%; 50.45% / 71.01% | 29.71% / 47.57%; 32.23% / 71.05% | 18.41% / 48.09%; 20.92% / 71.55% | 10.80% / 49.93%; 13.30% / 73.37% |
| classified data seller tier 0/1 endpoint revenue quiet | N | 8.39% / 73.40%; 10.85% / 111.48% | 6.54% / 73.08%; 8.86% / 111.05% | 5.84% / 73.40%; 8.10% / 111.34% | 5.49% / 74.37%; 7.73% / 112.29% | 5.29% / 77.52%; 7.51% / 115.43% |
| classified data seller tier 0/1 endpoint revenue quiet | S | 72.96% / 75.00%; 75.33% / 111.69% | 44.59% / 73.22%; 46.87% / 111.20% | 27.49% / 73.52%; 29.73% / 111.46% | 17.10% / 74.48%; 19.32% / 112.40% | 10.18% / 77.62%; 12.40% / 115.54% |
| D94 | N | 8.38% / 36.80%; 8.65% / 60.19% | 8.14% / 36.15%; 8.40% / 59.53% | 7.95% / 35.95%; 8.21% / 59.52% | 5.85% / 35.88%; 6.11% / 59.90% | 4.57% / 35.96%; 4.82% / 61.48% |
| D94 | S | 95.00% / 48.31%; 95.27% / 77.27% | 93.73% / 46.54%; 93.99% / 74.66% | 92.47% / 44.09%; 92.73% / 70.12% | 88.74% / 44.03%; 89.00% / 70.13% | 82.84% / 42.68%; 83.10% / 68.81% |
| BlockRun(tier 1b) busy | N | 95.13% / 95.13%; 95.32% / 95.32% | 65.09% / 65.09%; 65.18% / 65.18% | 42.05% / 42.05%; 42.10% / 42.10% | 25.95% / 25.95%; 25.99% / 25.99% | 14.35% / 14.35%; 14.38% / 14.38% |
| BlockRun(tier 1b) busy | S | 106.24% / 106.24%; 106.43% / 106.43% | 105.98% / 105.98%; 106.07% / 106.07% | 105.89% / 105.89%; 105.94% / 105.94% | 105.84% / 105.84%; 105.88% / 105.88% | 105.42% / 105.42%; 105.44% / 105.44% |
| BlockRun(tier 1b) median | N | 78.11% / 78.11%; 78.22% / 78.22% | 50.94% / 50.94%; 51.00% / 51.00% | 33.60% / 33.60%; 33.64% / 33.64% | 22.14% / 22.14%; 22.18% / 22.18% | 11.30% / 11.30%; 11.33% / 11.33% |
| BlockRun(tier 1b) median | S | 102.01% / 102.01%; 102.12% / 102.12% | 101.89% / 101.89%; 101.96% / 101.96% | 101.86% / 101.86%; 101.90% / 101.90% | 101.86% / 101.86%; 101.89% / 101.89% | 101.64% / 101.64%; 101.66% / 101.66% |
| BlockRun(tier 1b) quiet | N | 4.71% / 4.71%; 5.15% / 5.15% | 3.64% / 3.64%; 4.06% / 4.06% | 2.70% / 2.70%; 3.10% / 3.10% | 2.02% / 2.02%; 2.41% / 2.41% | 1.49% / 1.49%; 1.86% / 1.86% |
| BlockRun(tier 1b) quiet | S | 90.00% / 90.00%; 90.44% / 90.44% | 79.17% / 79.17%; 79.59% / 79.59% | 61.91% / 61.91%; 62.31% / 62.31% | 41.97% / 41.97%; 42.35% / 42.35% | 20.10% / 20.10%; 20.48% / 20.48% |

## 7. cost optimum (V, k) and retention payment (σ 1, w 0.00173, facilitator none; K11 columns same point old gas value)

| window | seller | case | mode | V* | k* | total | K11 V* | K11 k* | K11 total | same k V 1 total | b | R/W_b × H(k*) | L USDC | L / R | L days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 3.00% | 5 | 32 | 2.49% | 3.67% | 5.00 | 21.4703 | 26.4703 | 1.81% | 0.38 |
| busy | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 10.37% | 5 | 32 | 9.85% | 35.02% | 5.00 | 276.1031 | 281.1031 | 19.27% | 4.05 |
| busy | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 4.20% | 5 | 1 | 3.59% | 4.89% | 5.00 | 6.5146 | 11.5146 | 0.79% | 0.17 |
| busy | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 11.56% | 5 | 1 | 10.95% | 36.25% | 5.00 | 261.1474 | 266.1474 | 18.24% | 3.83 |
| busy | OneSource | lower | N | 5 (grid end) | 32 | 21.55% | 5 | 32 | 17.47% | 22.67% | 5.00 | 0.4548 | 5.4548 | 17.65% | 3.71 |
| busy | OneSource | lower | S | 5 (grid end) | 32 | 21.56% | 5 | 32 | 17.49% | 22.30% | 5.00 | 5.8491 | 10.8491 | 35.10% | 7.37 |
| busy | OneSource | upper | N | 5 (grid end) | 1 | 27.89% | 5 | 1 | 23.25% | 29.27% | 5.00 | 0.1380 | 5.1380 | 16.62% | 3.49 |
| busy | OneSource | upper | S | 5 (grid end) | 1 | 27.84% | 5 | 1 | 23.21% | 28.62% | 5.00 | 5.5322 | 10.5322 | 34.08% | 7.16 |
| busy | CoinMarketCap | lower | N | 5 (grid end) | 32 | 25.55% | 5 | 32 | 22.00% | 25.69% | 5.00 | 0.6419 | 5.6419 | 12.93% | 2.72 |
| busy | CoinMarketCap | lower | S | 5 (grid end) | 32 | 25.88% | 5 | 32 | 22.33% | 26.91% | 5.00 | 8.2552 | 13.2552 | 30.39% | 6.38 |
| busy | CoinMarketCap | upper | N | 5 (grid end) | 1 | 46.16% | 5 | 1 | 40.92% | 46.32% | 5.00 | 0.1948 | 5.1948 | 11.91% | 2.50 |
| busy | CoinMarketCap | upper | S | 5 (grid end) | 1 | 46.49% | 5 | 1 | 41.25% | 47.55% | 5.00 | 7.8081 | 12.8081 | 29.36% | 6.17 |
| busy | StableApify | lower | N | 1 | 1 | 19.66% | 1 | 1 | 17.40% | 19.66% | 1.00 | 0.0134 | 1.0134 | 33.84% | 7.11 |
| busy | StableApify | lower | S | 1 | 1 | 19.84% | 1 | 1 | 17.58% | 19.84% | 1.00 | 0.5361 | 1.5361 | 51.29% | 10.77 |
| busy | StableApify | upper | N | 1 | 1 | 28.42% | 1 | 1 | 25.15% | 28.42% | 1.00 | 0.0134 | 1.0134 | 33.84% | 7.11 |
| busy | StableApify | upper | S | 1 | 1 | 28.59% | 1 | 1 | 25.33% | 28.59% | 1.00 | 0.5361 | 1.5361 | 51.29% | 10.77 |
| busy | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 805.04% | 0.2 | 32 | 719.33% | 806.14% | 0.20 | 0.0035 | 0.2035 | 86.58% | 18.18 |
| busy | Exa(0.001 or less) | lower | S | 0.2 (grid end) | 32 | 805.17% | 0.2 | 32 | 719.46% | 806.25% | 0.20 | 0.0445 | 0.2445 | 104.03% | 21.85 |
| busy | Exa(0.001 or less) | upper | N | 0.5 | 1 | 1411.41% | 0.2 | 1 | 1268.64% | 1412.38% | 0.50 | 0.0010 | 0.5010 | 213.21% | 44.77 |
| busy | Exa(0.001 or less) | upper | S | 0.5 | 1 | 1411.52% | 0.2 | 1 | 1268.77% | 1412.49% | 0.50 | 0.0421 | 0.5421 | 230.67% | 48.44 |
| busy | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 295.09% | 0.2 | 1 | 264.19% | 301.21% | 0.20 | 0.0003 | 0.2003 | 303.48% | 63.73 |
| busy | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 295.20% | 0.2 | 1 | 264.30% | 301.31% | 0.20 | 0.0118 | 0.2118 | 320.93% | 67.40 |
| busy | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 441.61% | 0.2 | 1 | 394.03% | 447.59% | 0.20 | 0.0003 | 0.2003 | 303.48% | 63.73 |
| busy | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 441.72% | 0.2 | 1 | 394.14% | 447.69% | 0.20 | 0.0118 | 0.2118 | 320.93% | 67.40 |
| busy | BlockRun | lower | N | 5 (grid end) | 4 | 14.35% | 5 | 4 | 13.02% | 42.05% | 5.00 | 574.8772 | 579.8772 | 0.55% | 0.12 |
| busy | BlockRun | lower | S | 5 (grid end) | 4 | 105.42% | 5 | 4 | 104.09% | 105.89% | 5.00 | 18960.2660 | 18965.2660 | 18.00% | 3.78 |
| busy | BlockRun | upper | N | 5 (grid end) | 1 | 14.38% | 5 | 1 | 13.05% | 42.10% | 5.00 | 470.3752 | 475.3752 | 0.45% | 0.09 |
| busy | BlockRun | upper | S | 5 (grid end) | 1 | 105.44% | 5 | 1 | 104.12% | 105.94% | 5.00 | 18855.7640 | 18860.7640 | 17.90% | 3.76 |
| median | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 3.45% | 5 | 32 | 2.87% | 4.00% | 5.00 | 16.6984 | 21.6984 | 1.91% | 0.40 |
| median | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 9.25% | 5 | 32 | 8.67% | 29.43% | 5.00 | 214.7382 | 219.7382 | 19.37% | 4.07 |
| median | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 5.08% | 5 | 1 | 4.38% | 5.67% | 5.00 | 5.0667 | 10.0667 | 0.89% | 0.19 |
| median | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 10.88% | 5 | 1 | 10.18% | 31.09% | 5.00 | 203.1065 | 208.1065 | 18.34% | 3.85 |
| median | OneSource | lower | N | 5 (grid end) | 32 | 28.39% | 5 | 32 | 23.11% | 29.57% | 5.00 | 1.1953 | 6.1953 | 7.63% | 1.60 |
| median | OneSource | lower | S | 5 (grid end) | 32 | 28.66% | 5 | 32 | 23.39% | 30.49% | 5.00 | 15.3718 | 20.3718 | 25.08% | 5.27 |
| median | OneSource | upper | N | 5 (grid end) | 1 | 40.35% | 5 | 1 | 34.09% | 41.79% | 5.00 | 0.3627 | 5.3627 | 6.60% | 1.39 |
| median | OneSource | upper | S | 5 (grid end) | 1 | 40.56% | 5 | 1 | 34.31% | 42.42% | 5.00 | 14.5391 | 19.5391 | 24.06% | 5.05 |
| median | CoinMarketCap | lower | N | 1 | 1 | 43.61% | 0.5 | 1 | 39.02% | 43.61% | 1.00 | 0.0073 | 1.0073 | 61.80% | 12.98 |
| median | CoinMarketCap | lower | S | 1 | 1 | 43.76% | 1 | 1 | 39.20% | 43.76% | 1.00 | 0.2918 | 1.2918 | 79.25% | 16.64 |
| median | CoinMarketCap | upper | N | 1 | 1 | 64.72% | 0.5 | 1 | 57.72% | 64.72% | 1.00 | 0.0073 | 1.0073 | 61.80% | 12.98 |
| median | CoinMarketCap | upper | S | 1 | 1 | 64.87% | 1 | 1 | 57.86% | 64.87% | 1.00 | 0.2918 | 1.2918 | 79.25% | 16.64 |
| median | StableApify | lower | N | 0.5 | 1 | 51.03% | 0.5 | 1 | 45.94% | 51.28% | 0.50 | 0.0028 | 0.5028 | 80.45% | 16.89 |
| median | StableApify | lower | S | 0.5 | 1 | 51.16% | 0.5 | 1 | 46.08% | 51.39% | 0.50 | 0.1119 | 0.6119 | 97.90% | 20.56 |
| median | StableApify | upper | N | 0.5 | 1 | 76.90% | 0.5 | 1 | 68.84% | 77.11% | 0.50 | 0.0028 | 0.5028 | 80.45% | 16.89 |
| median | StableApify | upper | S | 0.5 | 1 | 77.03% | 0.5 | 1 | 68.98% | 77.23% | 0.50 | 0.1119 | 0.6119 | 97.90% | 20.56 |
| median | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 787.20% | 0.2 | 32 | 701.99% | 788.07% | 0.20 | 0.0039 | 0.2039 | 76.38% | 16.04 |
| median | Exa(0.001 or less) | lower | S | 0.5 | 32 | 787.32% | 0.2 | 32 | 702.13% | 788.18% | 0.50 | 0.0505 | 0.5505 | 206.19% | 43.30 |
| median | Exa(0.001 or less) | upper | N | 0.5 | 1 | 1401.68% | 0.2 | 1 | 1259.89% | 1402.50% | 0.50 | 0.0012 | 0.5012 | 187.71% | 39.42 |
| median | Exa(0.001 or less) | upper | S | 0.5 | 1 | 1401.79% | 0.2 | 1 | 1260.03% | 1402.61% | 0.50 | 0.0478 | 0.5478 | 205.17% | 43.08 |
| median | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 472.48% | 0.2 | 1 | 424.14% | 488.07% | 0.20 | 0.0001 | 0.2001 | 714.73% | 150.09 |
| median | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 472.59% | 0.2 | 1 | 424.25% | 488.17% | 0.20 | 0.0050 | 0.2050 | 732.19% | 153.76 |
| median | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 712.60% | 0.2 | 1 | 637.24% | 728.04% | 0.20 | 0.0001 | 0.2001 | 714.73% | 150.09 |
| median | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 712.70% | 0.2 | 1 | 637.34% | 728.14% | 0.20 | 0.0050 | 0.2050 | 732.19% | 153.76 |
| median | BlockRun | lower | N | 5 (grid end) | 4 | 11.30% | 5 | 4 | 10.92% | 33.60% | 5.00 | 698.0116 | 703.0116 | 0.55% | 0.12 |
| median | BlockRun | lower | S | 5 (grid end) | 4 | 101.64% | 5 | 4 | 101.26% | 101.86% | 5.00 | 23021.4137 | 23026.4137 | 18.00% | 3.78 |
| median | BlockRun | upper | N | 5 (grid end) | 1 | 11.33% | 5 | 1 | 10.95% | 33.64% | 5.00 | 571.1261 | 576.1261 | 0.45% | 0.09 |
| median | BlockRun | upper | S | 5 (grid end) | 1 | 101.66% | 5 | 1 | 101.28% | 101.90% | 5.00 | 22894.5281 | 22899.5281 | 17.90% | 3.76 |
| quiet | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 3.99% | 5 | 32 | 3.27% | 4.51% | 5.00 | 14.9670 | 19.9670 | 2.75% | 0.41 |
| quiet | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 9.21% | 5 | 32 | 8.49% | 27.65% | 5.00 | 192.4718 | 197.4718 | 27.18% | 4.08 |
| quiet | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 5.49% | 5 | 1 | 4.65% | 6.04% | 5.00 | 4.5413 | 9.5413 | 1.31% | 0.20 |
| quiet | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 10.72% | 5 | 1 | 9.87% | 29.18% | 5.00 | 182.0462 | 187.0462 | 25.75% | 3.86 |
| quiet | OneSource | lower | N | 5 (grid end) | 32 | 18.98% | 5 | 32 | 15.65% | 20.15% | 5.00 | 1.0359 | 6.0359 | 12.00% | 1.80 |
| quiet | OneSource | lower | S | 5 (grid end) | 32 | 19.19% | 5 | 32 | 15.87% | 20.79% | 5.00 | 13.3217 | 18.3217 | 36.44% | 5.47 |
| quiet | OneSource | upper | N | 5 (grid end) | 1 | 27.99% | 5 | 1 | 23.92% | 29.42% | 5.00 | 0.3143 | 5.3143 | 10.57% | 1.59 |
| quiet | OneSource | upper | S | 5 (grid end) | 1 | 28.15% | 5 | 1 | 24.09% | 29.78% | 5.00 | 12.6001 | 17.6001 | 35.00% | 5.25 |
| quiet | CoinMarketCap | lower | N | 0.5 | 1 | 73.40% | 0.5 | 1 | 66.32% | 73.40% | 0.50 | 0.0059 | 0.5059 | 53.26% | 7.99 |
| quiet | CoinMarketCap | lower | S | 1 | 1 | 73.53% | 0.5 | 1 | 66.49% | 73.53% | 1.00 | 0.2381 | 1.2381 | 130.32% | 19.55 |
| quiet | CoinMarketCap | upper | N | 1 | 1 | 111.45% | 0.5 | 1 | 99.99% | 111.45% | 1.00 | 0.0059 | 1.0059 | 105.89% | 15.88 |
| quiet | CoinMarketCap | upper | S | 1 | 1 | 111.59% | 0.5 | 1 | 100.16% | 111.59% | 1.00 | 0.2381 | 1.2381 | 130.32% | 19.55 |
| quiet | StableApify | lower | N | 0.5 | 1 | 72.76% | 0.2 | 1 | 65.61% | 73.40% | 0.50 | 0.0015 | 0.5015 | 208.96% | 31.34 |
| quiet | StableApify | lower | S | 0.5 | 1 | 72.88% | 0.2 | 1 | 65.75% | 73.51% | 0.50 | 0.0601 | 0.5601 | 233.39% | 35.01 |
| quiet | StableApify | upper | N | 0.5 | 1 | 110.62% | 0.5 | 1 | 99.27% | 111.23% | 0.50 | 0.0015 | 0.5015 | 208.96% | 31.34 |
| quiet | StableApify | upper | S | 0.5 | 1 | 110.74% | 0.5 | 1 | 99.39% | 111.34% | 0.50 | 0.0601 | 0.5601 | 233.39% | 35.01 |
| quiet | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 928.63% | 0.2 | 32 | 828.36% | 929.62% | 0.20 | 0.0037 | 0.2037 | 114.42% | 17.16 |
| quiet | Exa(0.001 or less) | lower | S | 0.2 (grid end) | 32 | 928.76% | 0.2 | 32 | 828.49% | 929.73% | 0.20 | 0.0472 | 0.2472 | 138.86% | 20.83 |
| quiet | Exa(0.001 or less) | upper | N | 0.5 | 1 | 1688.39% | 0.2 | 1 | 1519.40% | 1689.30% | 0.50 | 0.0011 | 0.5011 | 281.52% | 42.23 |
| quiet | Exa(0.001 or less) | upper | S | 0.5 | 1 | 1688.51% | 0.2 | 1 | 1519.54% | 1689.41% | 0.50 | 0.0446 | 0.5446 | 305.96% | 45.89 |
| quiet | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 351.19% | 0.2 | 1 | 313.12% | 380.22% | 0.20 | 0.0001 | 0.2001 | 1818.81% | 272.82 |
| quiet | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 351.29% | 0.2 | 1 | 313.23% | 380.32% | 0.20 | 0.0028 | 0.2028 | 1843.24% | 276.49 |
| quiet | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 534.49% | 0.2 | 1 | 477.67% | 563.38% | 0.20 | 0.0001 | 0.2001 | 1818.81% | 272.82 |
| quiet | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 534.59% | 0.2 | 1 | 477.77% | 563.48% | 0.20 | 0.0028 | 0.2028 | 1843.24% | 276.49 |
| quiet | BlockRun | lower | N | 5 (grid end) | 32 | 1.49% | 5 | 32 | 1.30% | 2.70% | 5.00 | 58.4451 | 63.4451 | 2.24% | 0.34 |
| quiet | BlockRun | lower | S | 5 (grid end) | 32 | 20.10% | 5 | 32 | 19.92% | 61.91% | 5.00 | 751.5918 | 756.5918 | 26.67% | 4.00 |
| quiet | BlockRun | upper | N | 5 (grid end) | 1 | 1.86% | 5 | 1 | 1.65% | 3.10% | 5.00 | 17.7336 | 22.7336 | 0.80% | 0.12 |
| quiet | BlockRun | upper | S | 5 (grid end) | 1 | 20.48% | 5 | 1 | 20.27% | 62.31% | 5.00 | 710.8803 | 715.8803 | 25.24% | 3.79 |

set optimal V (all seller same V, per seller k; lower pooled min) and retention payment sum:

| set | mode | V* | lower pooled | median | Σb | Σ R/W_b H(k) | ΣL USDC | ΣL / ΣR | K11 V* | K11 pooled |
|---|---|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | N | 5 | 4.19% | 23.55% | 30.00 | 22.58 | 52.58 | 3.42% | 5 | 3.50% |
| classified data seller tier 0/1 endpoint revenue busy | S | 5 | 11.19% | 23.72% | 30.00 | 290.80 | 320.80 | 20.88% | 5 | 10.50% |
| classified data seller tier 0/1 endpoint revenue median | N | 5 | 5.38% | 49.82% | 30.00 | 17.91 | 47.91 | 3.93% | 5 | 4.46% |
| classified data seller tier 0/1 endpoint revenue median | S | 5 | 10.80% | 49.93% | 30.00 | 230.57 | 260.57 | 21.39% | 5 | 9.88% |
| classified data seller tier 0/1 endpoint revenue quiet | N | 5 | 5.29% | 77.52% | 30.00 | 16.01 | 46.01 | 5.91% | 5 | 4.37% |
| classified data seller tier 0/1 endpoint revenue quiet | S | 5 | 10.18% | 77.62% | 30.00 | 206.14 | 236.14 | 30.35% | 5 | 9.26% |
| D94 | N | 5 | 4.57% | 35.96% | 470.00 | 792.30 | 1262.30 | 1.24% | 5 | 4.40% |
| D94 | S | 5 | 82.84% | 42.68% | 470.00 | 18554.42 | 19024.42 | 18.69% | 5 | 82.67% |

## 8. K11 relative to difference (K11b − K11, %p; facilitator none)

| window | V | seller | case | mode | K11 | K11b | difference | K11 k | K11b k |
|---|---|---|---|---|---|---|---|---|---|
| busy | 0.2 | StableEnrich(Out candidates excluded) | lower | N | 6.02% | 6.89% | +0.86 | 32 | 32 |
| busy | 0.2 | StableEnrich(Out candidates excluded) | lower | S | 87.80% | 88.66% | +0.86 | 32 | 32 |
| busy | 0.2 | StableEnrich(Out candidates excluded) | upper | N | 7.28% | 8.25% | +0.96 | 1 | 1 |
| busy | 0.2 | StableEnrich(Out candidates excluded) | upper | S | 89.06% | 90.02% | +0.96 | 1 | 1 |
| busy | 0.2 | OneSource | lower | N | 23.93% | 28.61% | +4.68 | 32 | 32 |
| busy | 0.2 | OneSource | lower | S | 21.89% | 26.32% | +4.42 | 32 | 32 |
| busy | 0.2 | OneSource | upper | N | 31.25% | 36.50% | +5.25 | 1 | 1 |
| busy | 0.2 | OneSource | upper | S | 27.78% | 32.77% | +4.99 | 1 | 1 |
| busy | 0.2 | CoinMarketCap | lower | N | 22.70% | 26.61% | +3.91 | 32 | 32 |
| busy | 0.2 | CoinMarketCap | lower | S | 28.28% | 32.19% | +3.91 | 32 | 32 |
| busy | 0.2 | CoinMarketCap | upper | N | 41.78% | 47.38% | +5.60 | 1 | 1 |
| busy | 0.2 | CoinMarketCap | upper | S | 47.37% | 52.97% | +5.60 | 1 | 1 |
| busy | 0.2 | StableApify | lower | N | 17.81% | 20.37% | +2.56 | 1 | 1 |
| busy | 0.2 | StableApify | lower | S | 18.30% | 20.85% | +2.56 | 1 | 1 |
| busy | 0.2 | StableApify | upper | N | 25.69% | 29.26% | +3.57 | 1 | 1 |
| busy | 0.2 | StableApify | upper | S | 26.18% | 29.75% | +3.57 | 1 | 1 |
| busy | 0.2 | Exa(0.001 or less) | lower | N | 719.33% | 805.04% | +85.71 | 32 | 32 |
| busy | 0.2 | Exa(0.001 or less) | lower | S | 719.46% | 805.17% | +85.71 | 32 | 32 |
| busy | 0.2 | Exa(0.001 or less) | upper | N | 1268.64% | 1411.42% | +142.78 | 1 | 1 |
| busy | 0.2 | Exa(0.001 or less) | upper | S | 1268.77% | 1411.55% | +142.78 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | lower | N | 264.19% | 295.09% | +30.90 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | lower | S | 264.30% | 295.20% | +30.90 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | upper | N | 394.03% | 441.61% | +47.58 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | upper | S | 394.14% | 441.72% | +47.58 | 1 | 1 |
| busy | 0.2 | BlockRun | lower | N | 93.81% | 95.13% | +1.33 | 4 | 4 |
| busy | 0.2 | BlockRun | lower | S | 104.92% | 106.24% | +1.33 | 4 | 4 |
| busy | 0.2 | BlockRun | upper | N | 93.99% | 95.32% | +1.33 | 1 | 1 |
| busy | 0.2 | BlockRun | upper | S | 105.10% | 106.43% | +1.33 | 1 | 1 |
| busy | 1 | StableEnrich(Out candidates excluded) | lower | N | 3.10% | 3.67% | +0.57 | 32 | 32 |
| busy | 1 | StableEnrich(Out candidates excluded) | lower | S | 34.45% | 35.02% | +0.57 | 32 | 32 |
| busy | 1 | StableEnrich(Out candidates excluded) | upper | N | 4.22% | 4.89% | +0.67 | 1 | 1 |
| busy | 1 | StableEnrich(Out candidates excluded) | upper | S | 35.58% | 36.25% | +0.67 | 1 | 1 |
| busy | 1 | OneSource | lower | N | 18.49% | 22.67% | +4.17 | 32 | 32 |
| busy | 1 | OneSource | lower | S | 18.18% | 22.30% | +4.12 | 32 | 32 |
| busy | 1 | OneSource | upper | N | 24.53% | 29.27% | +4.74 | 1 | 1 |
| busy | 1 | OneSource | upper | S | 23.92% | 28.62% | +4.69 | 1 | 1 |
| busy | 1 | CoinMarketCap | lower | N | 22.08% | 25.69% | +3.61 | 32 | 32 |
| busy | 1 | CoinMarketCap | lower | S | 23.30% | 26.91% | +3.61 | 32 | 32 |
| busy | 1 | CoinMarketCap | upper | N | 41.02% | 46.32% | +5.30 | 1 | 1 |
| busy | 1 | CoinMarketCap | upper | S | 42.25% | 47.55% | +5.30 | 1 | 1 |
| busy | 1 | StableApify | lower | N | 17.40% | 19.66% | +2.26 | 1 | 1 |
| busy | 1 | StableApify | lower | S | 17.58% | 19.84% | +2.26 | 1 | 1 |
| busy | 1 | StableApify | upper | N | 25.15% | 28.42% | +3.27 | 1 | 1 |
| busy | 1 | StableApify | upper | S | 25.33% | 28.59% | +3.27 | 1 | 1 |
| busy | 1 | Exa(0.001 or less) | lower | N | 720.74% | 806.14% | +85.41 | 32 | 32 |
| busy | 1 | Exa(0.001 or less) | lower | S | 720.84% | 806.25% | +85.41 | 32 | 32 |
| busy | 1 | Exa(0.001 or less) | upper | N | 1269.90% | 1412.38% | +142.48 | 1 | 1 |
| busy | 1 | Exa(0.001 or less) | upper | S | 1270.01% | 1412.49% | +142.48 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | lower | N | 270.61% | 301.21% | +30.60 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | lower | S | 270.71% | 301.31% | +30.60 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | upper | N | 400.31% | 447.59% | +47.28 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | upper | S | 400.41% | 447.69% | +47.28 | 1 | 1 |
| busy | 1 | BlockRun | lower | N | 40.72% | 42.05% | +1.33 | 4 | 4 |
| busy | 1 | BlockRun | lower | S | 104.56% | 105.89% | +1.33 | 4 | 4 |
| busy | 1 | BlockRun | upper | N | 40.77% | 42.10% | +1.33 | 1 | 1 |
| busy | 1 | BlockRun | upper | S | 104.61% | 105.94% | +1.33 | 1 | 1 |
| median | 0.2 | StableEnrich(Out candidates excluded) | lower | N | 5.50% | 6.39% | +0.89 | 32 | 32 |
| median | 0.2 | StableEnrich(Out candidates excluded) | lower | S | 77.05% | 77.94% | +0.89 | 32 | 32 |
| median | 0.2 | StableEnrich(Out candidates excluded) | upper | N | 7.15% | 8.17% | +1.03 | 1 | 1 |
| median | 0.2 | StableEnrich(Out candidates excluded) | upper | S | 78.70% | 79.72% | +1.03 | 1 | 1 |
| median | 0.2 | OneSource | lower | N | 29.72% | 35.61% | +5.89 | 32 | 32 |
| median | 0.2 | OneSource | lower | S | 33.73% | 39.36% | +5.64 | 32 | 32 |
| median | 0.2 | OneSource | upper | N | 42.25% | 49.11% | +6.86 | 1 | 1 |
| median | 0.2 | OneSource | upper | S | 44.82% | 51.43% | +6.61 | 1 | 1 |
| median | 0.2 | CoinMarketCap | lower | N | 39.33% | 44.19% | +4.86 | 1 | 1 |
| median | 0.2 | CoinMarketCap | lower | S | 39.65% | 44.50% | +4.86 | 1 | 1 |
| median | 0.2 | CoinMarketCap | upper | N | 58.14% | 65.44% | +7.30 | 1 | 1 |
| median | 0.2 | CoinMarketCap | upper | S | 58.45% | 65.75% | +7.30 | 1 | 1 |
| median | 0.2 | StableApify | lower | N | 46.09% | 51.40% | +5.31 | 1 | 1 |
| median | 0.2 | StableApify | lower | S | 46.27% | 51.58% | +5.31 | 1 | 1 |
| median | 0.2 | StableApify | upper | N | 69.09% | 77.37% | +8.28 | 1 | 1 |
| median | 0.2 | StableApify | upper | S | 69.27% | 77.55% | +8.28 | 1 | 1 |
| median | 0.2 | Exa(0.001 or less) | lower | N | 701.99% | 787.20% | +85.21 | 32 | 32 |
| median | 0.2 | Exa(0.001 or less) | lower | S | 702.13% | 787.34% | +85.21 | 32 | 32 |
| median | 0.2 | Exa(0.001 or less) | upper | N | 1259.89% | 1401.78% | +141.88 | 1 | 1 |
| median | 0.2 | Exa(0.001 or less) | upper | S | 1260.03% | 1401.91% | +141.88 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | lower | N | 424.14% | 472.48% | +48.34 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | lower | S | 424.25% | 472.59% | +48.34 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | upper | N | 637.24% | 712.60% | +75.36 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | upper | S | 637.34% | 712.70% | +75.36 | 1 | 1 |
| median | 0.2 | BlockRun | lower | N | 77.74% | 78.11% | +0.38 | 4 | 4 |
| median | 0.2 | BlockRun | lower | S | 101.63% | 102.01% | +0.38 | 4 | 4 |
| median | 0.2 | BlockRun | upper | N | 77.84% | 78.22% | +0.38 | 1 | 1 |
| median | 0.2 | BlockRun | upper | S | 101.74% | 102.12% | +0.38 | 1 | 1 |
| median | 1 | StableEnrich(Out candidates excluded) | lower | N | 3.37% | 4.00% | +0.63 | 32 | 32 |
| median | 1 | StableEnrich(Out candidates excluded) | lower | S | 28.79% | 29.43% | +0.63 | 32 | 32 |
| median | 1 | StableEnrich(Out candidates excluded) | upper | N | 4.90% | 5.67% | +0.77 | 1 | 1 |
| median | 1 | StableEnrich(Out candidates excluded) | upper | S | 30.33% | 31.09% | +0.77 | 1 | 1 |
| median | 1 | OneSource | lower | N | 24.19% | 29.57% | +5.39 | 32 | 32 |
| median | 1 | OneSource | lower | S | 25.16% | 30.49% | +5.34 | 32 | 32 |
| median | 1 | OneSource | upper | N | 35.43% | 41.79% | +6.36 | 1 | 1 |
| median | 1 | OneSource | upper | S | 36.11% | 42.42% | +6.31 | 1 | 1 |
| median | 1 | CoinMarketCap | lower | N | 39.06% | 43.61% | +4.55 | 1 | 1 |
| median | 1 | CoinMarketCap | lower | S | 39.20% | 43.76% | +4.55 | 1 | 1 |
| median | 1 | CoinMarketCap | upper | N | 57.72% | 64.72% | +7.00 | 1 | 1 |
| median | 1 | CoinMarketCap | upper | S | 57.86% | 64.87% | +7.00 | 1 | 1 |
| median | 1 | StableApify | lower | N | 46.27% | 51.28% | +5.01 | 1 | 1 |
| median | 1 | StableApify | lower | S | 46.38% | 51.39% | +5.01 | 1 | 1 |
| median | 1 | StableApify | upper | N | 69.13% | 77.11% | +7.98 | 1 | 1 |
| median | 1 | StableApify | upper | S | 69.25% | 77.23% | +7.98 | 1 | 1 |
| median | 1 | Exa(0.001 or less) | lower | N | 703.16% | 788.07% | +84.91 | 32 | 32 |
| median | 1 | Exa(0.001 or less) | lower | S | 703.27% | 788.18% | +84.91 | 32 | 32 |
| median | 1 | Exa(0.001 or less) | upper | N | 1260.92% | 1402.50% | +141.58 | 1 | 1 |
| median | 1 | Exa(0.001 or less) | upper | S | 1261.03% | 1402.61% | +141.58 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | lower | N | 440.03% | 488.07% | +48.04 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | lower | S | 440.13% | 488.17% | +48.04 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | upper | N | 652.98% | 728.04% | +75.06 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | upper | S | 653.09% | 728.14% | +75.06 | 1 | 1 |
| median | 1 | BlockRun | lower | N | 33.22% | 33.60% | +0.38 | 4 | 4 |
| median | 1 | BlockRun | lower | S | 101.48% | 101.86% | +0.38 | 4 | 4 |
| median | 1 | BlockRun | upper | N | 33.26% | 33.64% | +0.38 | 1 | 1 |
| median | 1 | BlockRun | upper | S | 101.52% | 101.90% | +0.38 | 1 | 1 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | lower | N | 5.77% | 6.82% | +1.05 | 32 | 32 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | lower | S | 74.76% | 75.81% | +1.05 | 32 | 32 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | upper | N | 7.30% | 8.48% | +1.17 | 1 | 1 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | upper | S | 76.29% | 77.46% | +1.17 | 1 | 1 |
| quiet | 0.2 | OneSource | lower | N | 22.23% | 26.17% | +3.93 | 32 | 32 |
| quiet | 0.2 | OneSource | lower | S | 24.97% | 28.65% | +3.68 | 32 | 32 |
| quiet | 0.2 | OneSource | upper | N | 32.06% | 36.73% | +4.68 | 1 | 1 |
| quiet | 0.2 | OneSource | upper | S | 33.36% | 37.78% | +4.42 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | lower | N | 66.61% | 73.91% | +7.30 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | lower | S | 66.88% | 74.18% | +7.30 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | upper | N | 100.38% | 112.10% | +11.72 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | upper | S | 100.66% | 112.38% | +11.72 | 1 | 1 |
| quiet | 0.2 | StableApify | lower | N | 65.61% | 72.89% | +7.28 | 1 | 1 |
| quiet | 0.2 | StableApify | lower | S | 65.75% | 73.03% | +7.28 | 1 | 1 |
| quiet | 0.2 | StableApify | upper | N | 99.28% | 110.85% | +11.58 | 1 | 1 |
| quiet | 0.2 | StableApify | upper | S | 99.42% | 111.00% | +11.58 | 1 | 1 |
| quiet | 0.2 | Exa(0.001 or less) | lower | N | 828.36% | 928.63% | +100.27 | 32 | 32 |
| quiet | 0.2 | Exa(0.001 or less) | lower | S | 828.49% | 928.76% | +100.27 | 32 | 32 |
| quiet | 0.2 | Exa(0.001 or less) | upper | N | 1519.40% | 1688.45% | +169.04 | 1 | 1 |
| quiet | 0.2 | Exa(0.001 or less) | upper | S | 1519.54% | 1688.58% | +169.04 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | lower | N | 313.12% | 351.19% | +38.06 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | lower | S | 313.23% | 351.29% | +38.06 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | upper | N | 477.67% | 534.49% | +56.82 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | upper | S | 477.77% | 534.59% | +56.82 | 1 | 1 |
| quiet | 0.2 | BlockRun | lower | N | 4.53% | 4.71% | +0.18 | 32 | 32 |
| quiet | 0.2 | BlockRun | lower | S | 89.82% | 90.00% | +0.18 | 32 | 32 |
| quiet | 0.2 | BlockRun | upper | N | 4.94% | 5.15% | +0.21 | 1 | 1 |
| quiet | 0.2 | BlockRun | upper | S | 90.22% | 90.44% | +0.21 | 1 | 1 |
| quiet | 1 | StableEnrich(Out candidates excluded) | lower | N | 3.73% | 4.51% | +0.78 | 32 | 32 |
| quiet | 1 | StableEnrich(Out candidates excluded) | lower | S | 26.87% | 27.65% | +0.78 | 32 | 32 |
| quiet | 1 | StableEnrich(Out candidates excluded) | upper | N | 5.13% | 6.04% | +0.90 | 1 | 1 |
| quiet | 1 | StableEnrich(Out candidates excluded) | upper | S | 28.27% | 29.18% | +0.90 | 1 | 1 |
| quiet | 1 | OneSource | lower | N | 16.72% | 20.15% | +3.43 | 32 | 32 |
| quiet | 1 | OneSource | lower | S | 17.42% | 20.79% | +3.38 | 32 | 32 |
| quiet | 1 | OneSource | upper | N | 25.25% | 29.42% | +4.17 | 1 | 1 |
| quiet | 1 | OneSource | upper | S | 25.66% | 29.78% | +4.12 | 1 | 1 |
| quiet | 1 | CoinMarketCap | lower | N | 66.40% | 73.40% | +7.00 | 1 | 1 |
| quiet | 1 | CoinMarketCap | lower | S | 66.53% | 73.53% | +7.00 | 1 | 1 |
| quiet | 1 | CoinMarketCap | upper | N | 100.03% | 111.45% | +11.42 | 1 | 1 |
| quiet | 1 | CoinMarketCap | upper | S | 100.17% | 111.59% | +11.42 | 1 | 1 |
| quiet | 1 | StableApify | lower | N | 66.42% | 73.40% | +6.98 | 1 | 1 |
| quiet | 1 | StableApify | lower | S | 66.53% | 73.51% | +6.98 | 1 | 1 |
| quiet | 1 | StableApify | upper | N | 99.95% | 111.23% | +11.28 | 1 | 1 |
| quiet | 1 | StableApify | upper | S | 100.06% | 111.34% | +11.28 | 1 | 1 |
| quiet | 1 | Exa(0.001 or less) | lower | N | 829.65% | 929.62% | +99.97 | 32 | 32 |
| quiet | 1 | Exa(0.001 or less) | lower | S | 829.76% | 929.73% | +99.97 | 32 | 32 |
| quiet | 1 | Exa(0.001 or less) | upper | N | 1520.56% | 1689.30% | +168.74 | 1 | 1 |
| quiet | 1 | Exa(0.001 or less) | upper | S | 1520.66% | 1689.41% | +168.74 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | lower | N | 342.45% | 380.22% | +37.76 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | lower | S | 342.56% | 380.32% | +37.76 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | upper | N | 506.86% | 563.38% | +56.52 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | upper | S | 506.96% | 563.48% | +56.52 | 1 | 1 |
| quiet | 1 | BlockRun | lower | N | 2.52% | 2.70% | +0.18 | 32 | 32 |
| quiet | 1 | BlockRun | lower | S | 61.73% | 61.91% | +0.18 | 32 | 32 |
| quiet | 1 | BlockRun | upper | N | 2.89% | 3.10% | +0.21 | 1 | 1 |
| quiet | 1 | BlockRun | upper | S | 62.10% | 62.31% | +0.21 | 1 | 1 |

set (pooled / median):

| set | V | case | mode | K11 | K11b | pooled difference | median difference |
|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | N | 7.00% / 23.31% | 8.05% / 27.61% | +1.05 | +4.30 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | S | 84.75% / 58.04% | 85.79% / 60.43% | +1.04 | +2.39 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | S-d | 72.26% / 50.59% | 73.30% / 52.98% | +1.04 | +2.39 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | S-120 | 49.43% / 37.96% | 50.48% / 40.73% | +1.05 | +2.77 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | N | 8.99% / 36.52% | 10.20% / 41.94% | +1.21 | +5.42 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | S | 86.71% / 68.21% | 87.91% / 71.49% | +1.20 | +3.28 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | S-d | 74.22% / 60.76% | 75.43% / 64.04% | +1.20 | +3.28 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | S-120 | 51.42% / 47.79% | 52.63% / 51.07% | +1.21 | +3.28 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | N | 4.10% / 20.28% | 4.84% / 24.18% | +0.75 | +3.89 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | S | 33.89% / 28.87% | 34.64% / 30.97% | +0.75 | +2.09 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | S-d | 25.16% / 24.08% | 25.91% / 26.18% | +0.75 | +2.09 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | S-120 | 15.31% / 20.65% | 16.06% / 24.54% | +0.75 | +3.89 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | N | 5.93% / 33.09% | 6.84% / 37.80% | +0.91 | +4.71 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | S | 35.72% / 38.91% | 36.63% / 41.90% | +0.91 | +2.98 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | S-d | 26.98% / 34.12% | 27.89% / 37.84% | +0.91 | +3.72 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | S-120 | 17.14% / 33.33% | 18.06% / 38.16% | +0.91 | +4.83 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | N | 7.34% / 42.71% | 8.59% / 47.79% | +1.25 | +5.08 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | S | 74.24% / 61.66% | 75.48% / 64.76% | +1.24 | +3.10 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | S-d | 60.51% / 54.37% | 61.75% / 57.48% | +1.24 | +3.10 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | S-120 | 39.85% / 43.16% | 41.11% / 47.89% | +1.25 | +4.73 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | N | 9.88% / 63.61% | 11.34% / 71.41% | +1.46 | +7.79 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | S | 76.68% / 73.98% | 78.12% / 78.64% | +1.44 | +4.65 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | S-d | 62.95% / 66.70% | 64.39% / 71.57% | +1.44 | +4.87 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | S-120 | 42.39% / 63.70% | 43.85% / 71.50% | +1.46 | +7.79 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | N | 4.99% / 42.66% | 5.97% / 47.45% | +0.98 | +4.78 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | S | 28.73% / 42.79% | 29.71% / 47.57% | +0.98 | +4.78 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | S-d | 21.54% / 42.75% | 22.52% / 47.54% | +0.98 | +4.78 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | S-120 | 13.72% / 42.71% | 14.70% / 47.50% | +0.98 | +4.78 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | N | 7.33% / 63.43% | 8.51% / 70.92% | +1.18 | +7.49 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | S | 31.05% / 63.56% | 32.23% / 71.05% | +1.18 | +7.49 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | S-d | 23.86% / 63.52% | 25.04% / 71.01% | +1.18 | +7.49 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | S-120 | 16.06% / 63.48% | 17.25% / 70.97% | +1.18 | +7.49 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | N | 7.12% / 66.11% | 8.39% / 73.40% | +1.27 | +7.29 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | S | 71.70% / 70.82% | 72.96% / 75.00% | +1.26 | +4.18 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | S-d | 57.92% / 66.25% | 59.17% / 73.54% | +1.26 | +7.29 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | S-120 | 37.80% / 66.19% | 39.07% / 73.48% | +1.27 | +7.29 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | N | 9.40% / 99.83% | 10.85% / 111.48% | +1.46 | +11.65 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | S | 73.89% / 100.04% | 75.33% / 111.69% | +1.44 | +11.65 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | S-d | 60.10% / 99.97% | 61.54% / 111.62% | +1.44 | +11.65 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | S-120 | 40.08% / 99.91% | 41.53% / 111.56% | +1.46 | +11.65 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | N | 4.85% / 66.41% | 5.84% / 73.40% | +0.99 | +6.99 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | S | 26.51% / 66.53% | 27.49% / 73.52% | +0.98 | +6.99 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | S-d | 19.88% / 66.50% | 20.86% / 73.49% | +0.98 | +6.99 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | S-120 | 12.75% / 66.46% | 13.73% / 73.45% | +0.99 | +6.99 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | N | 6.93% / 99.99% | 8.10% / 111.34% | +1.17 | +11.35 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | S | 28.56% / 100.12% | 29.73% / 111.46% | +1.17 | +11.35 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | S-d | 21.94% / 100.08% | 23.10% / 111.43% | +1.17 | +11.35 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | S-120 | 14.82% / 100.04% | 15.99% / 111.39% | +1.17 | +11.35 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | lower | N | 22.90% / 22.70% | 27.23% / 26.61% | +4.33 | +3.91 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | lower | S | 27.65% / 28.28% | 31.98% / 32.19% | +4.33 | +3.91 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | lower | S-d | 26.09% / 26.46% | 30.43% / 30.37% | +4.33 | +3.91 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | lower | S-120 | 24.52% / 24.60% | 28.85% / 28.51% | +4.33 | +3.91 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | upper | N | 38.01% / 41.78% | 43.74% / 47.38% | +5.73 | +5.60 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | upper | S | 42.75% / 47.37% | 48.48% / 52.97% | +5.73 | +5.60 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | upper | S-d | 41.20% / 45.54% | 46.93% / 51.14% | +5.73 | +5.60 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | upper | S-120 | 39.63% / 43.69% | 45.36% / 49.29% | +5.73 | +5.60 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | lower | N | 22.31% / 22.08% | 26.35% / 25.69% | +4.03 | +3.61 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | lower | S | 23.36% / 23.30% | 27.39% / 26.91% | +4.03 | +3.61 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | lower | S-d | 23.02% / 22.90% | 27.05% / 26.51% | +4.03 | +3.61 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | lower | S-120 | 22.67% / 22.50% | 26.71% / 26.11% | +4.03 | +3.61 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | upper | N | 37.28% / 41.02% | 42.71% / 46.32% | +5.43 | +5.30 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | upper | S | 38.33% / 42.25% | 43.76% / 47.55% | +5.43 | +5.30 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | upper | S-d | 37.99% / 41.84% | 43.42% / 47.14% | +5.43 | +5.30 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | upper | S-120 | 37.64% / 41.44% | 43.07% / 46.74% | +5.43 | +5.30 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | lower | N | 26.43% / 46.09% | 32.32% / 51.40% | +5.89 | +5.31 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | lower | S | 36.20% / 46.27% | 42.08% / 51.58% | +5.89 | +5.31 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | lower | S-d | 33.05% / 46.21% | 38.94% / 51.52% | +5.89 | +5.31 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | lower | S-120 | 29.81% / 46.16% | 35.70% / 51.47% | +5.89 | +5.31 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | upper | N | 39.57% / 69.09% | 46.66% / 77.37% | +7.09 | +8.28 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | upper | S | 49.34% / 69.27% | 56.42% / 77.55% | +7.09 | +8.28 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | upper | S-d | 46.19% / 69.22% | 53.28% / 77.50% | +7.09 | +8.28 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | upper | S-120 | 42.95% / 69.16% | 50.04% / 77.44% | +7.09 | +8.28 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | lower | N | 25.77% / 46.27% | 31.36% / 51.28% | +5.59 | +5.01 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | lower | S | 27.89% / 46.38% | 33.47% / 51.39% | +5.59 | +5.01 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | lower | S-d | 27.19% / 46.35% | 32.78% / 51.36% | +5.59 | +5.01 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | lower | S-120 | 26.49% / 46.31% | 32.08% / 51.32% | +5.59 | +5.01 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | upper | N | 38.77% / 69.13% | 45.56% / 77.11% | +6.79 | +7.98 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | upper | S | 40.89% / 69.25% | 47.68% / 77.23% | +6.79 | +7.98 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | upper | S-d | 40.19% / 69.21% | 46.98% / 77.20% | +6.79 | +7.98 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | upper | S-120 | 39.49% / 69.18% | 46.28% / 77.16% | +6.79 | +7.98 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | lower | N | 20.20% / 66.61% | 24.30% / 73.91% | +4.10 | +7.30 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | lower | S | 28.76% / 66.88% | 32.87% / 74.18% | +4.10 | +7.30 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | lower | S-d | 26.00% / 66.80% | 30.10% / 74.10% | +4.10 | +7.30 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | lower | S-120 | 23.15% / 66.71% | 27.25% / 74.01% | +4.10 | +7.30 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | upper | N | 31.55% / 100.38% | 36.72% / 112.10% | +5.17 | +11.72 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | upper | S | 40.12% / 100.66% | 45.28% / 112.38% | +5.17 | +11.72 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | upper | S-d | 37.35% / 100.57% | 42.51% / 112.29% | +5.17 | +11.72 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | upper | S-120 | 34.50% / 100.48% | 39.67% / 112.20% | +5.17 | +11.72 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | lower | N | 19.56% / 66.42% | 23.36% / 73.40% | +3.80 | +6.98 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | lower | S | 21.41% / 66.53% | 25.22% / 73.53% | +3.80 | +7.00 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | lower | S-d | 20.80% / 66.50% | 24.61% / 73.49% | +3.80 | +6.99 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | lower | S-120 | 20.19% / 66.47% | 23.99% / 73.45% | +3.80 | +6.99 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | upper | N | 30.77% / 100.03% | 35.64% / 111.45% | +4.87 | +11.42 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | upper | S | 32.63% / 100.17% | 37.50% / 111.59% | +4.87 | +11.42 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | upper | S-d | 32.02% / 100.13% | 36.88% / 111.55% | +4.87 | +11.42 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | upper | S-120 | 31.40% / 100.09% | 36.27% / 111.51% | +4.87 | +11.42 |
| D94 | 0.2 | lower | N | 8.18% / 31.01% | 8.38% / 36.80% | +0.20 | +5.79 |
| D94 | 0.2 | lower | S | 94.80% / 42.42% | 95.00% / 48.31% | +0.20 | +5.89 |
| D94 | 0.2 | lower | S-d | 91.04% / 42.28% | 91.24% / 47.95% | +0.20 | +5.67 |
| D94 | 0.2 | lower | S-120 | 76.97% / 40.13% | 77.17% / 44.94% | +0.20 | +4.81 |
| D94 | 0.2 | upper | N | 8.43% / 53.51% | 8.65% / 60.19% | +0.22 | +6.67 |
| D94 | 0.2 | upper | S | 95.05% / 72.07% | 95.27% / 77.27% | +0.22 | +5.20 |
| D94 | 0.2 | upper | S-d | 91.29% / 66.89% | 91.50% / 75.31% | +0.22 | +8.41 |
| D94 | 0.2 | upper | S-120 | 77.22% / 64.58% | 77.44% / 70.99% | +0.22 | +6.42 |
| D94 | 1 | lower | N | 7.77% / 30.51% | 7.95% / 35.95% | +0.18 | +5.43 |
| D94 | 1 | lower | S | 92.29% / 38.56% | 92.47% / 44.09% | +0.18 | +5.54 |
| D94 | 1 | lower | S-d | 88.28% / 38.44% | 88.46% / 43.98% | +0.18 | +5.54 |
| D94 | 1 | lower | S-120 | 74.02% / 37.07% | 74.21% / 43.22% | +0.18 | +6.15 |
| D94 | 1 | upper | N | 8.01% / 53.33% | 8.21% / 59.52% | +0.20 | +6.19 |
| D94 | 1 | upper | S | 92.53% / 62.77% | 92.73% / 70.12% | +0.20 | +7.35 |
| D94 | 1 | upper | S-d | 88.52% / 62.70% | 88.72% / 70.05% | +0.20 | +7.35 |
| D94 | 1 | upper | S-120 | 74.26% / 59.56% | 74.47% / 65.02% | +0.20 | +5.46 |
| K10 data(comparison) busy | 0.2 | lower | N | 6.70% / 17.84% | 7.73% / 21.33% | +1.03 | +3.49 |
| K10 data(comparison) busy | 0.2 | lower | S | 74.81% / 25.09% | 75.84% / 29.25% | +1.03 | +4.17 |
| K10 data(comparison) busy | 0.2 | lower | S-d | 63.79% / 23.51% | 64.82% / 27.68% | +1.03 | +4.17 |
| K10 data(comparison) busy | 0.2 | lower | S-120 | 43.70% / 21.92% | 44.73% / 26.09% | +1.03 | +4.17 |
| K10 data(comparison) busy | 0.2 | upper | N | 9.02% / 25.32% | 10.24% / 29.01% | +1.22 | +3.69 |
| K10 data(comparison) busy | 0.2 | upper | S | 77.12% / 39.81% | 78.35% / 44.27% | +1.22 | +4.46 |
| K10 data(comparison) busy | 0.2 | upper | S-d | 66.11% / 37.71% | 67.33% / 42.17% | +1.22 | +4.46 |
| K10 data(comparison) busy | 0.2 | upper | S-120 | 46.02% / 35.57% | 47.24% / 40.03% | +1.22 | +4.46 |
| K10 data(comparison) busy | 1 | lower | N | 4.26% / 17.34% | 5.03% / 20.53% | +0.76 | +3.19 |
| K10 data(comparison) busy | 1 | lower | S | 30.69% / 20.74% | 31.46% / 24.61% | +0.76 | +3.87 |
| K10 data(comparison) busy | 1 | lower | S-d | 22.95% / 20.39% | 23.71% / 23.98% | +0.76 | +3.59 |
| K10 data(comparison) busy | 1 | lower | S-120 | 14.20% / 17.53% | 14.96% / 20.72% | +0.76 | +3.19 |
| K10 data(comparison) busy | 1 | upper | N | 6.46% / 24.65% | 7.42% / 28.07% | +0.96 | +3.42 |
| K10 data(comparison) busy | 1 | upper | S | 32.89% / 30.74% | 33.85% / 32.58% | +0.96 | +1.84 |
| K10 data(comparison) busy | 1 | upper | S-d | 25.14% / 25.89% | 26.10% / 28.43% | +0.96 | +2.54 |
| K10 data(comparison) busy | 1 | upper | S-120 | 16.39% / 24.96% | 17.35% / 28.26% | +0.96 | +3.30 |
| K10 data(comparison) median | 0.2 | lower | N | 5.39% / 23.67% | 6.36% / 29.30% | +0.96 | +5.64 |
| K10 data(comparison) median | 0.2 | lower | S | 51.82% / 39.65% | 52.78% / 44.50% | +0.96 | +4.86 |
| K10 data(comparison) median | 0.2 | lower | S-d | 42.10% / 39.55% | 43.07% / 44.40% | +0.96 | +4.86 |
| K10 data(comparison) median | 0.2 | lower | S-120 | 27.54% / 39.45% | 28.50% / 41.06% | +0.96 | +1.61 |
| K10 data(comparison) median | 0.2 | upper | N | 7.57% / 34.76% | 8.73% / 41.37% | +1.15 | +6.61 |
| K10 data(comparison) median | 0.2 | upper | S | 54.00% / 58.45% | 55.15% / 65.75% | +1.15 | +7.30 |
| K10 data(comparison) median | 0.2 | upper | S-d | 44.28% / 58.35% | 45.44% / 65.21% | +1.15 | +6.87 |
| K10 data(comparison) median | 0.2 | upper | S-120 | 29.72% / 41.81% | 30.87% / 44.85% | +1.15 | +3.03 |
| K10 data(comparison) median | 1 | lower | N | 4.02% / 22.98% | 4.79% / 28.31% | +0.77 | +5.34 |
| K10 data(comparison) median | 1 | lower | S | 21.04% / 28.79% | 21.81% / 30.49% | +0.77 | +1.70 |
| K10 data(comparison) median | 1 | lower | S-d | 15.87% / 24.44% | 16.64% / 29.78% | +0.77 | +5.34 |
| K10 data(comparison) median | 1 | lower | S-120 | 10.22% / 23.72% | 10.99% / 29.05% | +0.77 | +5.34 |
| K10 data(comparison) median | 1 | upper | N | 6.11% / 33.93% | 7.07% / 40.24% | +0.96 | +6.31 |
| K10 data(comparison) median | 1 | upper | S | 23.13% / 36.11% | 24.08% / 42.42% | +0.96 | +6.31 |
| K10 data(comparison) median | 1 | upper | S-d | 17.96% / 35.39% | 18.91% / 41.70% | +0.96 | +6.31 |
| K10 data(comparison) median | 1 | upper | S-120 | 12.31% / 34.67% | 13.27% / 40.98% | +0.96 | +6.31 |
| K10 data(comparison) quiet | 0.2 | lower | N | 5.11% / 16.18% | 6.07% / 19.86% | +0.95 | +3.68 |
| K10 data(comparison) quiet | 0.2 | lower | S | 49.36% / 40.88% | 50.31% / 47.22% | +0.95 | +6.34 |
| K10 data(comparison) quiet | 0.2 | lower | S-d | 39.78% / 40.35% | 40.74% / 46.68% | +0.95 | +6.34 |
| K10 data(comparison) quiet | 0.2 | lower | S-120 | 25.79% / 38.42% | 26.74% / 39.47% | +0.95 | +1.05 |
| K10 data(comparison) quiet | 0.2 | upper | N | 7.01% / 24.56% | 8.13% / 28.98% | +1.12 | +4.42 |
| K10 data(comparison) quiet | 0.2 | upper | S | 51.26% / 72.78% | 52.37% / 77.46% | +1.12 | +4.68 |
| K10 data(comparison) quiet | 0.2 | upper | S-d | 41.68% / 61.72% | 42.80% / 62.89% | +1.12 | +1.17 |
| K10 data(comparison) quiet | 0.2 | upper | S-120 | 27.69% / 39.95% | 28.81% / 41.13% | +1.12 | +1.17 |
| K10 data(comparison) quiet | 1 | lower | N | 3.79% / 15.51% | 4.54% / 18.89% | +0.75 | +3.38 |
| K10 data(comparison) quiet | 1 | lower | S | 19.13% / 26.87% | 19.88% / 27.65% | +0.75 | +0.78 |
| K10 data(comparison) quiet | 1 | lower | S-d | 14.43% / 19.81% | 15.18% / 20.59% | +0.75 | +0.78 |
| K10 data(comparison) quiet | 1 | lower | S-120 | 9.34% / 16.16% | 10.09% / 19.54% | +0.75 | +3.38 |
| K10 data(comparison) quiet | 1 | upper | N | 5.59% / 23.75% | 6.51% / 27.87% | +0.91 | +4.12 |
| K10 data(comparison) quiet | 1 | upper | S | 20.94% / 28.27% | 21.85% / 29.78% | +0.91 | +1.50 |
| K10 data(comparison) quiet | 1 | upper | S-d | 16.23% / 25.03% | 17.14% / 29.15% | +0.91 | +4.12 |
| K10 data(comparison) quiet | 1 | upper | S-120 | 11.14% / 24.40% | 12.05% / 28.52% | +0.91 | +4.12 |

## 9. 10% threshold w* (σ 1, facilitator none; lower / upper; K11 → K11b "K11 | K11b" column)

| set | statistics | mode | V | K11 | K11b |
|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | pooled | N | 0.2 | 0.00349 / 0.00232 | 0.00287 / 0.00162 |
| classified data seller tier 0/1 endpoint revenue busy | pooled | N | 1 | 0.0153 / 0.0111 | 0.0136 / 0.00895 |
| classified data seller tier 0/1 endpoint revenue busy | pooled | S | 0.2 | 6.06e-05 / 4.06e-05 | 4.99e-05 / 2.85e-05 |
| classified data seller tier 0/1 endpoint revenue busy | pooled | S | 1 | 0.000322 / 0.000231 | 0.000285 / 0.000186 |
| classified data seller tier 0/1 endpoint revenue busy | median | N | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue busy | median | N | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue busy | median | S | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue busy | median | S | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | pooled | N | 0.2 | 0.0039 / 0.00183 | 0.00287 / 0.000661 |
| classified data seller tier 0/1 endpoint revenue median | pooled | N | 1 | 0.0158 / 0.00915 | 0.013 / 0.00585 |
| classified data seller tier 0/1 endpoint revenue median | pooled | S | 0.2 | 7.31e-05 / 3.79e-05 | 5.51e-05 / 1.74e-05 |
| classified data seller tier 0/1 endpoint revenue median | pooled | S | 1 | 0.000356 / 0.000206 | 0.000293 / 0.000132 |
| classified data seller tier 0/1 endpoint revenue median | median | N | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | median | N | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | median | S | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | median | S | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | N | 0.2 | 0.00424 / 0.00225 | 0.00312 / 0.001 |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | N | 1 | 0.0173 / 0.0109 | 0.0143 / 0.00741 |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | S | 0.2 | 7.98e-05 / 4.58e-05 | 6.02e-05 / 2.38e-05 |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | S | 1 | 0.000403 / 0.000254 | 0.000332 / 0.000172 |
| classified data seller tier 0/1 endpoint revenue quiet | median | N | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | median | N | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | median | S | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | median | S | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | pooled | N | 0.2 | 0.00218 / 0.00211 | 0.00213 / 0.00206 |
| D94 | pooled | N | 1 | 0.00231 / 0.00224 | 0.00226 / 0.00219 |
| D94 | pooled | S | 0.2 | 3.52e-05 / 3.42e-05 | 3.44e-05 / 3.33e-05 |
| D94 | pooled | S | 1 | 3.76e-05 / 3.65e-05 | 3.68e-05 / 3.56e-05 |
| D94 | median | N | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | median | N | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | median | S | 0.2 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | median | S | 1 | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| BlockRun(tier 1b) busy | pooled | N | 0.2 | 4.31e-05 / 4.16e-05 | 3.22e-05 / 3.07e-05 |
| BlockRun(tier 1b) busy | pooled | N | 1 | 0.000225 / 0.000223 | 0.000172 / 0.000169 |
| BlockRun(tier 1b) busy | pooled | S | 0.2 | 6.9e-07 / 6.65e-07 | 5.12e-07 / 4.87e-07 |
| BlockRun(tier 1b) busy | pooled | S | 1 | 3.62e-06 / 3.59e-06 | 2.75e-06 / 2.71e-06 |
| BlockRun(tier 1b) median | pooled | N | 0.2 | 0.000108 / 0.000106 | 0.000103 / 0.000101 |
| BlockRun(tier 1b) median | pooled | N | 1 | 0.000411 / 0.000409 | 0.000393 / 0.000391 |
| BlockRun(tier 1b) median | pooled | S | 0.2 | 1.74e-06 / 1.71e-06 | 1.66e-06 / 1.63e-06 |
| BlockRun(tier 1b) median | pooled | S | 1 | 6.65e-06 / 6.62e-06 | 6.35e-06 / 6.32e-06 |
| BlockRun(tier 1b) quiet | pooled | N | 0.2 | 0.00451 / 0.00429 | 0.00441 / 0.00418 |
| BlockRun(tier 1b) quiet | pooled | N | 1 | 0.00982 / 0.00941 | 0.00962 / 0.00917 |
| BlockRun(tier 1b) quiet | pooled | S | 0.2 | 7.43e-05 / 7.07e-05 | 7.27e-05 / 6.89e-05 |
| BlockRun(tier 1b) quiet | pooled | S | 1 | 0.000176 / 0.000168 | 0.000172 / 0.000164 |

## 10. verdict 2 (T01t pooled ≤ 10%, facilitator none, V 0.2 and 1, lower and upper)

| edition | mode | case | V | busy | median | quiet | verdict |
|---|---|---|---|---|---|---|---|
| K11 | N | lower | 0.2 | 7.00% | 7.34% | 7.12% | holds |
| K11 | N | lower | 1 | 4.10% | 4.99% | 4.85% | holds |
| K11 | N | upper | 0.2 | 8.99% | 9.88% | 9.40% | holds |
| K11 | N | upper | 1 | 5.93% | 7.33% | 6.93% | holds |
| K11 | S | lower | 0.2 | 84.75% | 74.24% | 71.70% | does not hold not |
| K11 | S | lower | 1 | 33.89% | 28.73% | 26.51% | does not hold not |
| K11 | S | upper | 0.2 | 86.71% | 76.68% | 73.89% | does not hold not |
| K11 | S | upper | 1 | 35.72% | 31.05% | 28.56% | does not hold not |
| K11b | N | lower | 0.2 | 8.05% | 8.59% | 8.39% | holds |
| K11b | N | lower | 1 | 4.84% | 5.97% | 5.84% | holds |
| K11b | N | upper | 0.2 | 10.20% | 11.34% | 10.85% | does not hold not |
| K11b | N | upper | 1 | 6.84% | 8.51% | 8.10% | holds |
| K11b | S | lower | 0.2 | 85.79% | 75.48% | 72.96% | does not hold not |
| K11b | S | lower | 1 | 34.64% | 29.71% | 27.49% | does not hold not |
| K11b | S | upper | 0.2 | 87.91% | 78.12% | 75.33% | does not hold not |
| K11b | S | upper | 1 | 36.63% | 32.23% | 29.73% | does not hold not |

## 11. p_max floor 1 gwei (D2): signature client preliminary (dispute gas only new value, L1 wei K11 and equal)

dispute open 1 KB 166,809 gas(K11 122,222), decryption dispute 4 KB 187,750 gas(K11 186,500). open purchase one preliminary: p_max 1 gwei 0.851522 USD(K11 0.741447), 0.0161 gwei 0.013778 USD.


## 12. component (pooled; K11b / K11)

| set | V | case | mode | verify | anchor | sampvrf | release | l1 | detincl | failpath | frozen | deduct | capital | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | N | 0.0115 / 0.0078 | 0.0278 / 0.0208 | 0.0072 / 0.0075 | 0.0033 / 0.0033 | 0.0002 / 0.0002 | - | - | 0.0287 / 0.0287 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0805 / 0.0700 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | S | 0.0102 / 0.0066 | 0.0278 / 0.0208 | 0.0072 / 0.0075 | 0.0033 / 0.0033 | 0.0002 / 0.0002 | - | - | 0.8064 / 0.8064 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.8579 / 0.8475 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | N | 0.0118 / 0.0081 | 0.0278 / 0.0208 | 0.0211 / 0.0198 | 0.0090 / 0.0090 | 0.0002 / 0.0002 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.0287 / 0.0287 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.1020 / 0.0899 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | S | 0.0102 / 0.0066 | 0.0278 / 0.0208 | 0.0211 / 0.0198 | 0.0090 / 0.0090 | 0.0002 / 0.0002 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.8064 / 0.8064 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 0.8791 / 0.8671 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | N | 0.0023 / 0.0016 | 0.0278 / 0.0208 | 0.0072 / 0.0075 | 0.0031 / 0.0031 | 0.0002 / 0.0002 | - | - | 0.0059 / 0.0059 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0484 / 0.0410 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | S | 0.0021 / 0.0013 | 0.0278 / 0.0208 | 0.0072 / 0.0075 | 0.0031 / 0.0031 | 0.0002 / 0.0002 | - | - | 0.3031 / 0.3031 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.3464 / 0.3389 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | N | 0.0024 / 0.0016 | 0.0278 / 0.0208 | 0.0211 / 0.0198 | 0.0089 / 0.0089 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0059 / 0.0059 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.0684 / 0.0593 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | S | 0.0021 / 0.0013 | 0.0278 / 0.0208 | 0.0211 / 0.0198 | 0.0089 / 0.0089 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.3031 / 0.3031 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.3663 / 0.3572 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | N | 0.0136 / 0.0101 | 0.0370 / 0.0276 | 0.0091 / 0.0095 | 0.0042 / 0.0042 | 0.0002 / 0.0002 | - | - | 0.0201 / 0.0201 | 0.0016 / 0.0016 | 0.0001 / 0.0001 | 0.0859 / 0.0734 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | S | 0.0094 / 0.0060 | 0.0370 / 0.0276 | 0.0091 / 0.0095 | 0.0042 / 0.0042 | 0.0002 / 0.0002 | - | - | 0.6922 / 0.6922 | 0.0016 / 0.0016 | 0.0011 / 0.0011 | 0.7548 / 0.7424 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | N | 0.0146 / 0.0110 | 0.0370 / 0.0276 | 0.0267 / 0.0251 | 0.0116 / 0.0116 | 0.0002 / 0.0002 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0201 / 0.0201 | 0.0016 / 0.0016 | 0.0000 / 0.0000 | 0.1134 / 0.0988 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | S | 0.0094 / 0.0060 | 0.0370 / 0.0276 | 0.0267 / 0.0251 | 0.0116 / 0.0116 | 0.0002 / 0.0002 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.6922 / 0.6922 | 0.0016 / 0.0016 | 0.0010 / 0.0010 | 0.7812 / 0.7668 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | N | 0.0029 / 0.0021 | 0.0370 / 0.0276 | 0.0091 / 0.0095 | 0.0041 / 0.0041 | 0.0002 / 0.0002 | - | - | 0.0045 / 0.0045 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0597 / 0.0499 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | S | 0.0021 / 0.0013 | 0.0370 / 0.0276 | 0.0091 / 0.0095 | 0.0041 / 0.0041 | 0.0002 / 0.0002 | - | - | 0.2418 / 0.2418 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.2971 / 0.2873 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | N | 0.0031 / 0.0023 | 0.0370 / 0.0276 | 0.0267 / 0.0251 | 0.0114 / 0.0114 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0045 / 0.0045 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0851 / 0.0733 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | S | 0.0021 / 0.0013 | 0.0370 / 0.0276 | 0.0267 / 0.0251 | 0.0114 / 0.0114 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.2418 / 0.2418 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.3223 / 0.3105 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | N | 0.0138 / 0.0101 | 0.0368 / 0.0274 | 0.0082 / 0.0085 | 0.0046 / 0.0046 | 0.0002 / 0.0002 | - | - | 0.0187 / 0.0187 | 0.0016 / 0.0016 | 0.0001 / 0.0001 | 0.0839 / 0.0712 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | S | 0.0097 / 0.0062 | 0.0368 / 0.0274 | 0.0082 / 0.0085 | 0.0046 / 0.0046 | 0.0002 / 0.0002 | - | - | 0.6674 / 0.6674 | 0.0016 / 0.0016 | 0.0011 / 0.0011 | 0.7296 / 0.7170 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | N | 0.0147 / 0.0111 | 0.0368 / 0.0274 | 0.0239 / 0.0225 | 0.0109 / 0.0109 | 0.0002 / 0.0002 | 0.0016 / 0.0016 | 0.0000 / 0.0000 | 0.0187 / 0.0187 | 0.0016 / 0.0016 | 0.0000 / 0.0000 | 0.1085 / 0.0940 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | S | 0.0097 / 0.0062 | 0.0368 / 0.0274 | 0.0239 / 0.0225 | 0.0109 / 0.0109 | 0.0002 / 0.0002 | 0.0016 / 0.0016 | 0.0000 / 0.0000 | 0.6674 / 0.6674 | 0.0016 / 0.0016 | 0.0010 / 0.0010 | 0.7533 / 0.7389 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | N | 0.0029 / 0.0021 | 0.0368 / 0.0274 | 0.0082 / 0.0085 | 0.0044 / 0.0044 | 0.0002 / 0.0002 | - | - | 0.0041 / 0.0041 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0584 / 0.0485 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | S | 0.0021 / 0.0013 | 0.0368 / 0.0274 | 0.0082 / 0.0085 | 0.0044 / 0.0044 | 0.0002 / 0.0002 | - | - | 0.2204 / 0.2204 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.2749 / 0.2651 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | N | 0.0031 / 0.0023 | 0.0368 / 0.0274 | 0.0239 / 0.0225 | 0.0107 / 0.0107 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0041 / 0.0041 | 0.0017 / 0.0017 | 0.0001 / 0.0001 | 0.0810 / 0.0693 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | S | 0.0021 / 0.0013 | 0.0368 / 0.0274 | 0.0239 / 0.0225 | 0.0107 / 0.0107 | 0.0002 / 0.0002 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.2204 / 0.2204 | 0.0017 / 0.0017 | 0.0011 / 0.0011 | 0.2973 / 0.2856 |
| D94 | 0.2 | lower | N | 0.0012 / 0.0007 | 0.0061 / 0.0045 | 0.0009 / 0.0010 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.0745 / 0.0745 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.0838 / 0.0818 |
| D94 | 0.2 | lower | S | 0.0012 / 0.0007 | 0.0061 / 0.0045 | 0.0009 / 0.0010 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.9397 / 0.9397 | 0.0002 / 0.0002 | 0.0011 / 0.0011 | 0.9500 / 0.9480 |
| D94 | 0.2 | upper | N | 0.0012 / 0.0007 | 0.0061 / 0.0045 | 0.0027 / 0.0026 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.0745 / 0.0745 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.0865 / 0.0843 |
| D94 | 0.2 | upper | S | 0.0012 / 0.0007 | 0.0061 / 0.0045 | 0.0027 / 0.0026 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.9397 / 0.9397 | 0.0002 / 0.0002 | 0.0010 / 0.0010 | 0.9527 / 0.9505 |
| D94 | 1 | lower | N | 0.0007 / 0.0005 | 0.0061 / 0.0045 | 0.0009 / 0.0010 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.0702 / 0.0702 | 0.0006 / 0.0006 | 0.0001 / 0.0001 | 0.0795 / 0.0777 |
| D94 | 1 | lower | S | 0.0007 / 0.0005 | 0.0061 / 0.0045 | 0.0009 / 0.0010 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.9144 / 0.9144 | 0.0006 / 0.0006 | 0.0011 / 0.0011 | 0.9247 / 0.9229 |
| D94 | 1 | upper | N | 0.0007 / 0.0005 | 0.0061 / 0.0045 | 0.0027 / 0.0026 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0001 / 0.0001 | 0.0000 / 0.0000 | 0.0702 / 0.0702 | 0.0006 / 0.0006 | 0.0000 / 0.0000 | 0.0821 / 0.0801 |
| D94 | 1 | upper | S | 0.0007 / 0.0005 | 0.0061 / 0.0045 | 0.0027 / 0.0026 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0001 / 0.0001 | 0.0000 / 0.0000 | 0.9144 / 0.9144 | 0.0006 / 0.0006 | 0.0010 / 0.0010 | 0.9273 / 0.9253 |
| BlockRun(tier 1b) busy | 0.2 | lower | N | 0.0043 / 0.0043 | 0.0482 / 0.0349 | 0.0001 / 0.0001 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | - | - | 0.8899 / 0.8899 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.9513 / 0.9381 |
| BlockRun(tier 1b) busy | 0.2 | lower | S | 0.0043 / 0.0043 | 0.0482 / 0.0349 | 0.0001 / 0.0001 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | - | - | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0624 / 1.0492 |
| BlockRun(tier 1b) busy | 0.2 | upper | N | 0.0043 / 0.0043 | 0.0482 / 0.0349 | 0.0003 / 0.0002 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.8899 / 0.8899 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.9532 / 0.9399 |
| BlockRun(tier 1b) busy | 0.2 | upper | S | 0.0043 / 0.0043 | 0.0482 / 0.0349 | 0.0003 / 0.0002 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0643 / 1.0510 |
| BlockRun(tier 1b) busy | 1 | lower | N | 0.0009 / 0.0009 | 0.0482 / 0.0349 | 0.0001 / 0.0001 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | - | - | 0.3626 / 0.3626 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.4205 / 0.4072 |
| BlockRun(tier 1b) busy | 1 | lower | S | 0.0009 / 0.0009 | 0.0482 / 0.0349 | 0.0001 / 0.0001 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | - | - | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0589 / 1.0456 |
| BlockRun(tier 1b) busy | 1 | upper | N | 0.0009 / 0.0009 | 0.0482 / 0.0349 | 0.0003 / 0.0002 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.3626 / 0.3626 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.4210 / 0.4077 |
| BlockRun(tier 1b) busy | 1 | upper | S | 0.0009 / 0.0009 | 0.0482 / 0.0349 | 0.0003 / 0.0002 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0594 / 1.0461 |
| BlockRun(tier 1b) median | 0.2 | lower | N | 0.0023 / 0.0023 | 0.0137 / 0.0099 | 0.0001 / 0.0001 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | - | - | 0.7620 / 0.7620 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7811 / 0.7774 |
| BlockRun(tier 1b) median | 0.2 | lower | S | 0.0023 / 0.0023 | 0.0137 / 0.0099 | 0.0001 / 0.0001 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | - | - | 1.0000 / 1.0000 | 0.0009 / 0.0009 | 0.0010 / 0.0010 | 1.0201 / 1.0163 |
| BlockRun(tier 1b) median | 0.2 | upper | N | 0.0023 / 0.0023 | 0.0137 / 0.0099 | 0.0002 / 0.0002 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7620 / 0.7620 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7822 / 0.7784 |
| BlockRun(tier 1b) median | 0.2 | upper | S | 0.0023 / 0.0023 | 0.0137 / 0.0099 | 0.0002 / 0.0002 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0009 / 0.0009 | 0.0010 / 0.0010 | 1.0212 / 1.0174 |
| BlockRun(tier 1b) median | 1 | lower | N | 0.0006 / 0.0006 | 0.0137 / 0.0099 | 0.0001 / 0.0001 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | - | - | 0.3184 / 0.3184 | 0.0012 / 0.0012 | 0.0000 / 0.0000 | 0.3360 / 0.3322 |
| BlockRun(tier 1b) median | 1 | lower | S | 0.0006 / 0.0006 | 0.0137 / 0.0099 | 0.0001 / 0.0001 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | - | - | 1.0000 / 1.0000 | 0.0012 / 0.0012 | 0.0010 / 0.0010 | 1.0186 / 1.0148 |
| BlockRun(tier 1b) median | 1 | upper | N | 0.0006 / 0.0006 | 0.0137 / 0.0099 | 0.0002 / 0.0002 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.3184 / 0.3184 | 0.0012 / 0.0012 | 0.0000 / 0.0000 | 0.3364 / 0.3326 |
| BlockRun(tier 1b) median | 1 | upper | S | 0.0006 / 0.0006 | 0.0137 / 0.0099 | 0.0002 / 0.0002 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0012 / 0.0012 | 0.0010 / 0.0010 | 1.0190 / 1.0152 |
| BlockRun(tier 1b) quiet | 0.2 | lower | N | 0.0018 / 0.0018 | 0.0073 / 0.0054 | 0.0013 / 0.0014 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | - | - | 0.0349 / 0.0349 | 0.0007 / 0.0007 | 0.0001 / 0.0001 | 0.0471 / 0.0453 |
| BlockRun(tier 1b) quiet | 0.2 | lower | S | 0.0018 / 0.0018 | 0.0073 / 0.0054 | 0.0013 / 0.0014 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | - | - | 0.8868 / 0.8868 | 0.0007 / 0.0007 | 0.0011 / 0.0011 | 0.9000 / 0.8982 |
| BlockRun(tier 1b) quiet | 0.2 | upper | N | 0.0018 / 0.0018 | 0.0073 / 0.0054 | 0.0039 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.0349 / 0.0349 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.0515 / 0.0494 |
| BlockRun(tier 1b) quiet | 0.2 | upper | S | 0.0018 / 0.0018 | 0.0073 / 0.0054 | 0.0039 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.8868 / 0.8868 | 0.0007 / 0.0007 | 0.0010 / 0.0010 | 0.9044 / 0.9022 |
| BlockRun(tier 1b) quiet | 1 | lower | N | 0.0008 / 0.0008 | 0.0073 / 0.0054 | 0.0013 / 0.0014 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.0151 / 0.0151 | 0.0015 / 0.0015 | 0.0001 / 0.0001 | 0.0270 / 0.0252 |
| BlockRun(tier 1b) quiet | 1 | lower | S | 0.0008 / 0.0008 | 0.0073 / 0.0054 | 0.0013 / 0.0014 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.6062 / 0.6062 | 0.0015 / 0.0015 | 0.0011 / 0.0011 | 0.6191 / 0.6173 |
| BlockRun(tier 1b) quiet | 1 | upper | N | 0.0008 / 0.0008 | 0.0073 / 0.0054 | 0.0039 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0151 / 0.0151 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0310 / 0.0289 |
| BlockRun(tier 1b) quiet | 1 | upper | S | 0.0008 / 0.0008 | 0.0073 / 0.0054 | 0.0039 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.6062 / 0.6062 | 0.0015 / 0.0015 | 0.0010 / 0.0010 | 0.6231 / 0.6210 |

## 13. sensitivity L, W, U, C (for verdicts not used not; pooled, lower / upper)

anchor transaction capacity: K11 CAP_GAS {1: 924, 0: 1564}, C {1: 752, 0: 1257}. capacity reaching added unit arising seller added unit sum(V 1, N): K11 {'T01t:busy': 0.0, 'T01t:median': 0.0, 'T01t:quiet': 30.0, 'D94': 0.0, 'BR:busy': 8936.0, 'BR:median': 1970.0, 'BR:quiet': 0.0}.

| set | V | mode | K11 | K11b | L | W | U | C |
|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | N | 7.00% / 8.99% | 8.05% / 10.20% | 8.05% / 10.20% | 8.33% / 10.48% | 8.05% / 10.08% | 8.05% / 10.20% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S | 84.75% / 86.71% | 85.79% / 87.91% | 85.79% / 87.92% | 86.08% / 88.20% | 85.79% / 87.80% | 85.79% / 87.91% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | N | 4.10% / 5.93% | 4.84% / 6.84% | 4.85% / 6.84% | 4.90% / 6.90% | 4.84% / 6.82% | 4.84% / 6.84% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S | 33.89% / 35.72% | 34.64% / 36.63% | 34.64% / 36.63% | 34.70% / 36.68% | 34.64% / 36.60% | 34.64% / 36.63% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | N | 7.34% / 9.88% | 8.59% / 11.34% | 8.60% / 11.34% | 8.84% / 11.58% | 8.59% / 11.23% | 8.59% / 11.34% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S | 74.24% / 76.68% | 75.48% / 78.12% | 75.48% / 78.12% | 75.74% / 78.38% | 75.48% / 78.02% | 75.48% / 78.12% |
| classified data seller tier 0/1 endpoint revenue median | 1 | N | 4.99% / 7.33% | 5.97% / 8.51% | 5.97% / 8.52% | 6.02% / 8.57% | 5.97% / 8.49% | 5.97% / 8.51% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S | 28.73% / 31.05% | 29.71% / 32.23% | 29.71% / 32.23% | 29.77% / 32.29% | 29.71% / 32.21% | 29.71% / 32.23% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | N | 7.12% / 9.40% | 8.39% / 10.85% | 8.39% / 10.86% | 8.64% / 11.10% | 8.39% / 10.74% | 8.40% / 10.86% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S | 71.70% / 73.89% | 72.96% / 75.33% | 72.96% / 75.33% | 73.23% / 75.60% | 72.96% / 75.22% | 72.96% / 75.33% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | N | 4.85% / 6.93% | 5.84% / 8.10% | 5.84% / 8.10% | 5.89% / 8.16% | 5.84% / 8.08% | 5.84% / 8.11% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S | 26.51% / 28.56% | 27.49% / 29.73% | 27.49% / 29.73% | 27.55% / 29.79% | 27.49% / 29.71% | 27.49% / 29.73% |
| BlockRun(tier 1b) busy | 0.2 | N | 93.81% / 93.99% | 95.13% / 95.32% | 95.13% / 95.32% | 95.78% / 95.97% | 95.13% / 95.21% | 95.14% / 95.33% |
| BlockRun(tier 1b) busy | 0.2 | S | 104.92% / 105.10% | 106.24% / 106.43% | 106.24% / 106.43% | 106.89% / 107.08% | 106.24% / 106.32% | 106.25% / 106.44% |
| BlockRun(tier 1b) busy | 1 | N | 40.72% / 40.77% | 42.05% / 42.10% | 42.05% / 42.10% | 42.18% / 42.23% | 42.05% / 42.08% | 42.06% / 42.11% |
| BlockRun(tier 1b) busy | 1 | S | 104.56% / 104.61% | 105.89% / 105.94% | 105.89% / 105.94% | 106.02% / 106.07% | 105.89% / 105.92% | 105.90% / 105.95% |
| BlockRun(tier 1b) median | 0.2 | N | 77.74% / 77.84% | 78.11% / 78.22% | 78.11% / 78.22% | 78.46% / 78.57% | 78.11% / 78.16% | 78.11% / 78.22% |
| BlockRun(tier 1b) median | 0.2 | S | 101.63% / 101.74% | 102.01% / 102.12% | 102.01% / 102.12% | 102.36% / 102.46% | 102.01% / 102.05% | 102.01% / 102.12% |
| BlockRun(tier 1b) median | 1 | N | 33.22% / 33.26% | 33.60% / 33.64% | 33.60% / 33.64% | 33.69% / 33.73% | 33.60% / 33.63% | 33.60% / 33.65% |
| BlockRun(tier 1b) median | 1 | S | 101.48% / 101.52% | 101.86% / 101.90% | 101.86% / 101.90% | 101.95% / 101.99% | 101.86% / 101.89% | 101.86% / 101.90% |
| BlockRun(tier 1b) quiet | 0.2 | N | 4.53% / 4.94% | 4.71% / 5.15% | 4.71% / 5.15% | 4.99% / 5.43% | 4.71% / 5.10% | 4.72% / 5.16% |
| BlockRun(tier 1b) quiet | 0.2 | S | 89.82% / 90.22% | 90.00% / 90.44% | 90.00% / 90.44% | 90.28% / 90.72% | 90.00% / 90.39% | 90.00% / 90.44% |
| BlockRun(tier 1b) quiet | 1 | N | 2.52% / 2.89% | 2.70% / 3.10% | 2.70% / 3.10% | 2.82% / 3.22% | 2.70% / 3.08% | 2.71% / 3.10% |
| BlockRun(tier 1b) quiet | 1 | S | 61.73% / 62.10% | 61.91% / 62.31% | 61.91% / 62.31% | 62.03% / 62.43% | 61.91% / 62.29% | 61.92% / 62.32% |
| D94 | 0.2 | N | 8.18% / 8.43% | 8.38% / 8.65% | 8.38% / 8.65% | 8.41% / 8.68% | 8.38% / 8.63% | 8.38% / 8.65% |
| D94 | 0.2 | S | 94.80% / 95.05% | 95.00% / 95.27% | 95.00% / 95.27% | 95.03% / 95.30% | 95.00% / 95.26% | 95.00% / 95.27% |
| D94 | 1 | N | 7.77% / 8.01% | 7.95% / 8.21% | 7.95% / 8.21% | 7.97% / 8.23% | 7.95% / 8.20% | 7.95% / 8.21% |
| D94 | 1 | S | 92.29% / 92.53% | 92.47% / 92.73% | 92.47% / 92.73% | 92.49% / 92.75% | 92.47% / 92.72% | 92.47% / 92.73% |

C added anchor unit arising set(V 1, N, added unit sum): T01t:busy 0, T01t:median 0, T01t:quiet 37, BR:busy 11298, BR:median 2845, BR:quiet 38, D94 0. K11b: T01t:busy 0, T01t:median 0, T01t:quiet 30, BR:busy 8936, BR:median 1970, BR:quiet 0, D94 0.

## 14. independent for checking three cell (rule: T01t and BlockRun, V 1, lower, mode N |K11b − K11| max cell, seller mutually differs)

constant: 1 gas = gp × 1e-9 × ETH USD, gp = 0.010 gwei, ETH 2401.44. 1 wei(L1) = 1e-18 × ETH USD. anchor(σ 1) run gas = 189907.00 + 21649.375 x, EIP-7623 lower gas = 34460.00 + 13731.250 x, two among large value(x = n / A_p). anchor L1 wei = A_p × 1870582712.0000 + n × 1566632536.1250. release gas = Ru × 114,624 + 2,930 n + 2,083 n_s, release L1 wei = Ru × 945606403.8667 + n × 245940057.8917. ECVRF sample = gusd(48,669 + 78,301) + wusd(734,567,965 + 2,593,604,493).

proof price: RS3 = gusd(86,824) + wusd(2,132,754,915) = 0.00209015 USD (K11 0.00133927). TEE = gusd(36,440) + wusd(2,157,333,560) = 0.00088027 USD. SP0(lower) = gusd(604,522) + wusd(28,173,828,378) + gusd(5,000) = 0.01470496 USD.

### quiet, Exa(0.001 or less), V 1, lower, mode N (K11b − K11 = +99.97%p)

- input: R = 0.178000 USDC, n = 178, n_s = 0.178000, days 15, E_p = 178, A_p = 178, chosen k = 32, Ru = 68, proof RS3 c_P = 0.00209015 USD, b = 1.000000, H(k) = 13,351, Δ_f = 2,251, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.002090, anchor 5.080399, sampvrf 3.057101, release 1.121977, l1 0.009712, frozen 0.000001, deduct 0.001730, capital 0.023172, total 9.296183 (= 929.62%)
- other k total: k 1 10.998589, k 2 10.998591, k 4 10.998595, k 8 10.998602, k 16 10.333109, k 32 9.296183

### median, CoinStats(0.01 or less), V 1, lower, mode N (K11b − K11 = +48.04%p)

- input: R = 0.028000 USDC, n = 28, n_s = 0.028000, days 21, E_p = 11, A_p = 11, chosen k = 1, Ru = 11, proof RS3 c_P = 0.00209015 USD, b = 1.000000, H(k) = 4,051, Δ_f = 2,251, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.002090, anchor 2.311523, sampvrf 1.201004, release 1.151801, l1 0.007010, frozen 0.000000, deduct 0.001730, capital 0.205505, total 4.880663 (= 488.07%)
- other k total: k 1 4.880663, k 2 4.880665, k 4 4.880669, k 8 4.880676, k 16 4.880691, k 32 4.880722

### quiet, CoinMarketCap, V 1, lower, mode N (K11b − K11 = +7.00%p)

- input: R = 0.950000 USDC, n = 95, n_s = 0.950000, days 15, E_p = 61, A_p = 61, chosen k = 1, Ru = 61, proof RS3 c_P = 0.00209015 USD, b = 1.000000, H(k) = 4,051, Δ_f = 2,251, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.002090, anchor 0.344822, sampvrf 0.196298, release 0.183834, l1 0.000870, frozen 0.000006, deduct 0.001730, capital 0.004352, total 0.734001 (= 73.40%)
- other k total: k 1 0.734001, k 2 0.734003, k 4 0.734007, k 8 0.734014, k 16 0.734029, k 32 0.734060

