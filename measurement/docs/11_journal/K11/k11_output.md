# K11 output (k11.py)

K11_settings.md SHA-256 9c6f1c9ca392afa81cf93f77d5a80c5c23534af0c4ddde09d50c8066e7350cbd. settings this run before were fixed(K11_results.md same value recorded).

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
| docs/11_journal/G10_gas/G10d_gas.md | 8dac8442 |
| docs/11_journal/rule10-candidate/F1_seller-stage-classes.csv | d15a67bd |
| docs/11_journal/K_revision-cost/K10/k10h.py | cdcc02ef |
| docs/11_journal/K_revision-cost/K10/k10h_output.md | 4741f9ea |

R10 list: none. per epoch sales count epochs_{busy,median}.csv.gz(600 s epoch), partial seller E1 k10h_output.md 2 (sec.) value busy StableEnrich 2046, busy Exa 195, busy CoinStats 16, median StableEnrich 2178, median Exa 220, median CoinStats 11.

## 1. K10h reproduction: old parameters(OLD: b = bond(V), a_A 20) k10h_output.md 3section and 6 (sec.) cells and comparison

| Table | cell count | equal |
|---|---|---|
| 3 (sec.) total | 256 | 256 |
| 6 (sec.) seller row | 216 | 216 |

OLD K10h 472cell among 472cells as is outputs.

## 2. mode parameters and retention, freeze interval (block, 2 s)

| mode | b | a_A | τ_V + 1 + T_V | T_p | T_c | H(1) | H(32) | Δ_f | H(1) time | Δ_f time | OneSource proof |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OLD | bond(V) = V/0.675 | 20 | 31 | 1,800 | 1,800 | 3,951 | 13,251 | 2,151 | 2.19 | 1.20 | SP0 |
| N | V | 120 | 31 | 1,800 | 1,800 | 4,051 | 13,351 | 2,251 | 2.25 | 1.25 | SP0 |
| S | V | 90,600 | 22,651 | 24,420 | 24,420 | 162,391 | 171,691 | 137,971 | 90.22 | 76.65 | RS3(signature feed kept) |
| S-d | V | 45,300 | 22,651 | 24,420 | 24,420 | 117,091 | 126,391 | 92,671 | 65.05 | 51.48 | RS3(signature feed kept) |
| S-120 | V | 120 | 22,651 | 24,420 | 24,420 | 71,911 | 81,211 | 47,491 | 39.95 | 26.38 | SP0 |

## 3. admission inspection (19) and related inspection (value: left side vs right side)

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

## 4. per seller and set total (revenue relative to %; σ 1, w 0.00173, r 10%, a 0, per seller optimal k)

k at lower chosen kc. "carry-over" facilitator gas to the seller passed value. S OneSource signature feed is a proof.

| window | V | seller | R USDC | n | N k | N lower | N upper | N lower carry-over | S k | S lower | S upper | S lower carry-over |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | 0.2 | StableEnrich(Out candidates excluded) | 1458.90 | 38369 | 32 | 6.02% | 7.28% | 9.97% | 32 | 87.80% | 89.06% | 91.74% |
| busy | 0.2 | OneSource | 30.91 | 7194 | 32 | 23.93% | 31.25% | 58.67% | 32 | 21.89% | 27.78% | 56.63% |
| busy | 0.2 | CoinMarketCap | 43.62 | 4362 | 32 | 22.70% | 41.78% | 38.48% | 32 | 28.28% | 47.37% | 44.07% |
| busy | 0.2 | StableApify | 3.00 | 193 | 1 | 17.81% | 25.69% | 27.94% | 1 | 18.30% | 26.18% | 28.42% |
| busy | 0.2 | Exa(0.001 or less) | 0.23 | 235 | 32 | 719.33% | 1268.64% | 901.15% | 32 | 719.46% | 1268.77% | 901.28% |
| busy | 0.2 | CoinStats(0.01 or less) | 0.07 | 45 | 1 | 264.19% | 394.03% | 374.90% | 1 | 264.30% | 394.14% | 375.01% |
| busy | 0.2 | BlockRun | 105338.04 | 9656870 | 4 | 93.81% | 93.99% | 107.36% | 4 | 104.92% | 105.10% | 118.47% |
| busy | 1 | StableEnrich(Out candidates excluded) | 1458.90 | 38369 | 32 | 3.10% | 4.22% | 7.04% | 32 | 34.45% | 35.58% | 38.40% |
| busy | 1 | OneSource | 30.91 | 7194 | 32 | 18.49% | 24.53% | 53.23% | 32 | 18.18% | 23.92% | 52.92% |
| busy | 1 | CoinMarketCap | 43.62 | 4362 | 32 | 22.08% | 41.02% | 37.86% | 32 | 23.30% | 42.25% | 39.09% |
| busy | 1 | StableApify | 3.00 | 193 | 1 | 17.40% | 25.15% | 27.53% | 1 | 17.58% | 25.33% | 27.71% |
| busy | 1 | Exa(0.001 or less) | 0.23 | 235 | 32 | 720.74% | 1269.90% | 902.55% | 32 | 720.84% | 1270.01% | 902.66% |
| busy | 1 | CoinStats(0.01 or less) | 0.07 | 45 | 1 | 270.61% | 400.31% | 381.32% | 1 | 270.71% | 400.41% | 381.42% |
| busy | 1 | BlockRun | 105338.04 | 9656870 | 4 | 40.72% | 40.77% | 54.27% | 4 | 104.56% | 104.61% | 118.11% |
| median | 0.2 | StableEnrich(Out candidates excluded) | 1134.66 | 31237 | 32 | 5.50% | 7.15% | 9.64% | 32 | 77.05% | 78.70% | 81.19% |
| median | 0.2 | OneSource | 81.22 | 22909 | 32 | 29.72% | 42.25% | 71.98% | 32 | 33.73% | 44.82% | 75.99% |
| median | 0.2 | CoinMarketCap | 1.63 | 163 | 1 | 39.33% | 58.14% | 55.57% | 1 | 39.65% | 58.45% | 55.88% |
| median | 0.2 | StableApify | 0.62 | 54 | 1 | 46.09% | 69.09% | 60.63% | 1 | 46.27% | 69.27% | 60.81% |
| median | 0.2 | Exa(0.001 or less) | 0.27 | 267 | 32 | 701.99% | 1259.89% | 883.57% | 32 | 702.13% | 1260.03% | 883.70% |
| median | 0.2 | CoinStats(0.01 or less) | 0.03 | 28 | 1 | 424.14% | 637.24% | 588.04% | 1 | 424.25% | 637.34% | 588.15% |
| median | 0.2 | BlockRun | 127900.66 | 3319274 | 4 | 77.74% | 77.84% | 81.57% | 4 | 101.63% | 101.74% | 105.47% |
| median | 1 | StableEnrich(Out candidates excluded) | 1134.66 | 31237 | 32 | 3.37% | 4.90% | 7.52% | 32 | 28.79% | 30.33% | 32.94% |
| median | 1 | OneSource | 81.22 | 22909 | 32 | 24.19% | 35.43% | 66.45% | 32 | 25.16% | 36.11% | 67.42% |
| median | 1 | CoinMarketCap | 1.63 | 163 | 1 | 39.06% | 57.72% | 55.30% | 1 | 39.20% | 57.86% | 55.44% |
| median | 1 | StableApify | 0.62 | 54 | 1 | 46.27% | 69.13% | 60.81% | 1 | 46.38% | 69.25% | 60.92% |
| median | 1 | Exa(0.001 or less) | 0.27 | 267 | 32 | 703.16% | 1260.92% | 884.74% | 32 | 703.27% | 1261.03% | 884.84% |
| median | 1 | CoinStats(0.01 or less) | 0.03 | 28 | 1 | 440.03% | 652.98% | 603.93% | 1 | 440.13% | 653.09% | 604.03% |
| median | 1 | BlockRun | 127900.66 | 3319274 | 4 | 33.22% | 33.26% | 37.06% | 4 | 101.48% | 101.52% | 105.32% |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | 726.43 | 27866 | 32 | 5.77% | 7.30% | 11.51% | 32 | 74.76% | 76.29% | 80.50% |
| quiet | 0.2 | OneSource | 50.28 | 8329 | 32 | 22.23% | 32.06% | 47.16% | 32 | 24.97% | 33.36% | 49.90% |
| quiet | 0.2 | CoinMarketCap | 0.95 | 95 | 1 | 66.61% | 100.38% | 84.02% | 1 | 66.88% | 100.66% | 84.29% |
| quiet | 0.2 | StableApify | 0.24 | 26 | 1 | 65.61% | 99.28% | 84.18% | 1 | 65.75% | 99.42% | 84.33% |
| quiet | 0.2 | Exa(0.001 or less) | 0.18 | 178 | 32 | 828.36% | 1519.40% | 1017.16% | 32 | 828.49% | 1519.54% | 1017.29% |
| quiet | 0.2 | CoinStats(0.01 or less) | 0.01 | 11 | 1 | 313.12% | 477.67% | 472.10% | 1 | 313.23% | 477.77% | 472.20% |
| quiet | 0.2 | BlockRun | 2836.67 | 28710 | 32 | 4.53% | 4.94% | 6.04% | 32 | 89.82% | 90.22% | 91.33% |
| quiet | 1 | StableEnrich(Out candidates excluded) | 726.43 | 27866 | 32 | 3.73% | 5.13% | 9.47% | 32 | 26.87% | 28.27% | 32.61% |
| quiet | 1 | OneSource | 50.28 | 8329 | 32 | 16.72% | 25.25% | 41.65% | 32 | 17.42% | 25.66% | 42.34% |
| quiet | 1 | CoinMarketCap | 0.95 | 95 | 1 | 66.40% | 100.03% | 83.81% | 1 | 66.53% | 100.17% | 83.94% |
| quiet | 1 | StableApify | 0.24 | 26 | 1 | 66.42% | 99.95% | 85.00% | 1 | 66.53% | 100.06% | 85.11% |
| quiet | 1 | Exa(0.001 or less) | 0.18 | 178 | 32 | 829.65% | 1520.56% | 1018.45% | 32 | 829.76% | 1520.66% | 1018.55% |
| quiet | 1 | CoinStats(0.01 or less) | 0.01 | 11 | 1 | 342.45% | 506.86% | 501.43% | 1 | 342.56% | 506.96% | 501.53% |
| quiet | 1 | BlockRun | 2836.67 | 28710 | 32 | 2.52% | 2.89% | 4.03% | 32 | 61.73% | 62.10% | 63.24% |

set pooled / median (lower; upper; lower carry-over):

| set | V | mode | lower pooled / median | upper pooled / median | lower carry-over pooled / median |
|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | OLD | 6.96% / 23.39% | 8.95% / 36.60% | 11.90% / 48.66% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | b only | 6.88% / 23.31% | 8.87% / 36.51% | 11.82% / 48.57% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | a_A only | 7.08% / 23.40% | 9.07% / 36.60% | 12.03% / 48.66% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | N | 7.00% / 23.31% | 8.99% / 36.52% | 11.94% / 48.57% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S | 84.75% / 58.04% | 86.71% / 68.21% | 89.69% / 74.19% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S-d | 72.26% / 50.59% | 74.22% / 60.76% | 77.21% / 66.99% |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | S-120 | 49.43% / 37.96% | 51.42% / 47.79% | 54.38% / 57.31% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | OLD | 4.15% / 20.37% | 5.99% / 33.22% | 9.10% / 45.64% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | b only | 4.07% / 20.28% | 5.90% / 33.09% | 9.01% / 45.55% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | a_A only | 4.18% / 20.37% | 6.01% / 33.22% | 9.12% / 45.64% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | N | 4.10% / 20.28% | 5.93% / 33.09% | 9.04% / 45.55% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S | 33.89% / 28.87% | 35.72% / 38.91% | 38.83% / 46.00% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S-d | 25.16% / 24.08% | 26.98% / 34.12% | 30.10% / 45.65% |
| classified data seller tier 0/1 endpoint revenue busy | 1 | S-120 | 15.31% / 20.65% | 17.14% / 33.33% | 20.26% / 45.91% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | OLD | 7.33% / 42.85% | 9.86% / 63.76% | 14.08% / 66.43% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | b only | 7.25% / 42.71% | 9.79% / 63.61% | 14.00% / 66.30% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | a_A only | 7.41% / 42.86% | 9.95% / 63.76% | 14.17% / 66.43% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | N | 7.34% / 42.71% | 9.88% / 63.61% | 14.09% / 66.31% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S | 74.24% / 61.66% | 76.68% / 73.98% | 80.99% / 78.59% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S-d | 60.51% / 54.37% | 62.95% / 66.70% | 67.26% / 69.72% |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | S-120 | 39.85% / 43.16% | 42.39% / 63.70% | 46.61% / 68.08% |
| classified data seller tier 0/1 endpoint revenue median | 1 | OLD | 5.06% / 43.05% | 7.39% / 63.82% | 11.81% / 63.93% |
| classified data seller tier 0/1 endpoint revenue median | 1 | b only | 4.97% / 42.66% | 7.31% / 63.43% | 11.72% / 63.63% |
| classified data seller tier 0/1 endpoint revenue median | 1 | a_A only | 5.08% / 43.05% | 7.41% / 63.82% | 11.83% / 63.94% |
| classified data seller tier 0/1 endpoint revenue median | 1 | N | 4.99% / 42.66% | 7.33% / 63.43% | 11.74% / 63.63% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S | 28.73% / 42.79% | 31.05% / 63.56% | 35.48% / 64.17% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S-d | 21.54% / 42.75% | 23.86% / 63.52% | 28.29% / 63.80% |
| classified data seller tier 0/1 endpoint revenue median | 1 | S-120 | 13.72% / 42.71% | 16.06% / 63.48% | 20.47% / 64.02% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | OLD | 7.11% / 66.30% | 9.39% / 100.02% | 14.16% / 84.29% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | b only | 7.04% / 66.11% | 9.31% / 99.83% | 14.08% / 84.10% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | a_A only | 7.20% / 66.30% | 9.47% / 100.02% | 14.24% / 84.29% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | N | 7.12% / 66.11% | 9.40% / 99.83% | 14.16% / 84.10% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S | 71.70% / 70.82% | 73.89% / 100.04% | 78.75% / 84.31% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S-d | 57.92% / 66.25% | 60.10% / 99.97% | 64.96% / 84.25% |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | S-120 | 37.80% / 66.19% | 40.08% / 99.91% | 44.84% / 84.18% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | OLD | 4.92% / 67.01% | 7.00% / 100.59% | 11.97% / 85.00% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | b only | 4.84% / 66.41% | 6.91% / 99.99% | 11.88% / 84.40% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | a_A only | 4.94% / 67.01% | 7.02% / 100.59% | 11.98% / 85.00% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | N | 4.85% / 66.41% | 6.93% / 99.99% | 11.90% / 84.40% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S | 26.51% / 66.53% | 28.56% / 100.12% | 33.55% / 84.52% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S-d | 19.88% / 66.50% | 21.94% / 100.08% | 26.92% / 84.49% |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | S-120 | 12.75% / 66.46% | 14.82% / 100.04% | 19.79% / 84.45% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | OLD | 22.98% / 22.78% | 38.09% / 41.86% | 46.66% / 52.70% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | b only | 22.90% / 22.69% | 38.00% / 41.78% | 46.58% / 52.61% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | a_A only | 22.99% / 22.78% | 38.10% / 41.87% | 46.67% / 52.70% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | N | 22.90% / 22.70% | 38.01% / 41.78% | 46.58% / 52.61% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S | 27.65% / 28.28% | 42.75% / 47.37% | 51.32% / 56.63% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S-d | 26.09% / 26.46% | 41.20% / 45.54% | 49.77% / 55.31% |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | S-120 | 24.52% / 24.60% | 39.63% / 43.69% | 48.20% / 53.98% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | OLD | 22.41% / 22.17% | 37.38% / 41.11% | 46.09% / 52.11% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | b only | 22.31% / 22.08% | 37.28% / 41.02% | 45.99% / 52.02% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | a_A only | 22.41% / 22.17% | 37.38% / 41.11% | 46.09% / 52.11% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | N | 22.31% / 22.08% | 37.28% / 41.02% | 45.99% / 52.02% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S | 23.36% / 23.30% | 38.33% / 42.25% | 47.04% / 52.92% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S-d | 23.02% / 22.90% | 37.99% / 41.84% | 46.69% / 52.62% |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | S-120 | 22.67% / 22.50% | 37.64% / 41.44% | 46.35% / 52.33% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | OLD | 26.51% / 46.26% | 39.65% / 69.26% | 68.55% / 66.01% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | b only | 26.43% / 46.09% | 39.57% / 69.09% | 68.46% / 65.92% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | a_A only | 26.52% / 46.26% | 39.66% / 69.26% | 68.56% / 66.01% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | N | 26.43% / 46.09% | 39.57% / 69.09% | 68.47% / 65.93% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S | 36.20% / 46.27% | 49.34% / 69.27% | 78.23% / 75.99% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S-d | 33.05% / 46.21% | 46.19% / 69.22% | 75.09% / 72.75% |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | S-120 | 29.81% / 46.16% | 42.95% / 69.16% | 71.85% / 69.41% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | OLD | 25.87% / 46.79% | 38.87% / 69.66% | 67.91% / 65.33% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | b only | 25.77% / 46.27% | 38.77% / 69.13% | 67.81% / 65.24% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | a_A only | 25.87% / 46.79% | 38.87% / 69.66% | 67.91% / 65.33% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | N | 25.77% / 46.27% | 38.77% / 69.13% | 67.81% / 65.24% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S | 27.89% / 46.38% | 40.89% / 69.25% | 69.92% / 67.42% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S-d | 27.19% / 46.35% | 40.19% / 69.21% | 69.23% / 66.70% |
| tier 0 and 1 data, StableEnrich excluded median | 1 | S-120 | 26.49% / 46.31% | 39.49% / 69.18% | 68.53% / 65.98% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | OLD | 20.28% / 66.73% | 31.63% / 100.51% | 45.63% / 84.43% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | b only | 20.19% / 66.61% | 31.54% / 100.38% | 45.54% / 84.18% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | a_A only | 20.29% / 66.73% | 31.64% / 100.51% | 45.64% / 84.43% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | N | 20.20% / 66.61% | 31.55% / 100.38% | 45.55% / 84.18% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S | 28.76% / 66.88% | 40.12% / 100.66% | 54.11% / 84.33% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S-d | 26.00% / 66.80% | 37.35% / 100.57% | 51.35% / 84.28% |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | S-120 | 23.15% / 66.71% | 34.50% / 100.48% | 48.50% / 84.24% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | OLD | 19.66% / 67.33% | 30.87% / 100.86% | 45.01% / 85.90% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | b only | 19.56% / 66.42% | 30.77% / 100.03% | 44.91% / 85.00% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | a_A only | 19.66% / 67.33% | 30.87% / 100.86% | 45.01% / 85.90% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | N | 19.56% / 66.42% | 30.77% / 100.03% | 44.91% / 85.00% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S | 21.41% / 66.53% | 32.63% / 100.17% | 46.77% / 85.11% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S-d | 20.80% / 66.50% | 32.02% / 100.13% | 46.15% / 85.07% |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | S-120 | 20.19% / 66.47% | 31.40% / 100.09% | 45.54% / 85.04% |
| D94 | 0.2 | OLD | 7.87% / 31.10% | 8.12% / 53.64% | 9.23% / 52.17% |
| D94 | 0.2 | b only | 7.86% / 31.01% | 8.11% / 53.51% | 9.22% / 52.07% |
| D94 | 0.2 | a_A only | 8.19% / 31.10% | 8.44% / 53.64% | 9.54% / 52.17% |
| D94 | 0.2 | N | 8.18% / 31.01% | 8.43% / 53.51% | 9.53% / 52.07% |
| D94 | 0.2 | S | 94.80% / 42.42% | 95.05% / 72.07% | 96.16% / 66.77% |
| D94 | 0.2 | S-d | 91.04% / 42.28% | 91.29% / 66.89% | 92.39% / 63.54% |
| D94 | 0.2 | S-120 | 76.97% / 40.13% | 77.22% / 64.58% | 78.33% / 58.34% |
| D94 | 1 | OLD | 7.50% / 30.64% | 7.74% / 53.68% | 8.85% / 51.71% |
| D94 | 1 | b only | 7.47% / 30.51% | 7.71% / 53.33% | 8.82% / 51.56% |
| D94 | 1 | a_A only | 7.80% / 30.64% | 8.04% / 53.68% | 9.15% / 51.72% |
| D94 | 1 | N | 7.77% / 30.51% | 8.01% / 53.33% | 9.12% / 51.56% |
| D94 | 1 | S | 92.29% / 38.56% | 92.53% / 62.77% | 93.64% / 58.23% |
| D94 | 1 | S-d | 88.28% / 38.44% | 88.52% / 62.70% | 89.63% / 58.18% |
| D94 | 1 | S-120 | 74.02% / 37.07% | 74.26% / 59.56% | 75.38% / 58.13% |
| K10 data(comparison) busy | 0.2 | OLD | 6.67% / 17.93% | 8.98% / 25.41% | 11.37% / 33.30% |
| K10 data(comparison) busy | 0.2 | b only | 6.59% / 17.84% | 8.91% / 25.31% | 11.29% / 33.21% |
| K10 data(comparison) busy | 0.2 | a_A only | 6.78% / 17.93% | 9.09% / 25.41% | 11.47% / 33.30% |
| K10 data(comparison) busy | 0.2 | N | 6.70% / 17.84% | 9.02% / 25.32% | 11.40% / 33.21% |
| K10 data(comparison) busy | 0.2 | S | 74.81% / 25.09% | 77.12% / 39.81% | 79.51% / 50.35% |
| K10 data(comparison) busy | 0.2 | S-d | 63.79% / 23.51% | 66.11% / 37.71% | 68.49% / 48.78% |
| K10 data(comparison) busy | 0.2 | S-120 | 43.70% / 21.92% | 46.02% / 35.57% | 48.40% / 47.18% |
| K10 data(comparison) busy | 1 | OLD | 4.32% / 17.47% | 6.52% / 24.78% | 9.02% / 32.83% |
| K10 data(comparison) busy | 1 | b only | 4.24% / 17.34% | 6.44% / 24.65% | 8.94% / 32.70% |
| K10 data(comparison) busy | 1 | a_A only | 4.35% / 17.48% | 6.54% / 24.78% | 9.05% / 32.83% |
| K10 data(comparison) busy | 1 | N | 4.26% / 17.34% | 6.46% / 24.65% | 8.96% / 32.70% |
| K10 data(comparison) busy | 1 | S | 30.69% / 20.74% | 32.89% / 30.74% | 35.39% / 38.80% |
| K10 data(comparison) busy | 1 | S-d | 22.95% / 20.39% | 25.14% / 25.89% | 27.64% / 33.99% |
| K10 data(comparison) busy | 1 | S-120 | 14.20% / 17.53% | 16.39% / 24.96% | 18.89% / 32.94% |
| K10 data(comparison) median | 0.2 | OLD | 5.39% / 23.74% | 7.57% / 34.83% | 10.36% / 55.69% |
| K10 data(comparison) median | 0.2 | b only | 5.33% / 23.66% | 7.51% / 34.75% | 10.31% / 55.57% |
| K10 data(comparison) median | 0.2 | a_A only | 5.45% / 23.75% | 7.63% / 34.84% | 10.42% / 55.69% |
| K10 data(comparison) median | 0.2 | N | 5.39% / 23.67% | 7.57% / 34.76% | 10.37% / 55.57% |
| K10 data(comparison) median | 0.2 | S | 51.82% / 39.65% | 54.00% / 58.45% | 56.79% / 60.81% |
| K10 data(comparison) median | 0.2 | S-d | 42.10% / 39.55% | 44.28% / 58.35% | 47.08% / 60.75% |
| K10 data(comparison) median | 0.2 | S-120 | 27.54% / 39.45% | 29.72% / 41.81% | 32.51% / 55.69% |
| K10 data(comparison) median | 1 | OLD | 4.08% / 23.06% | 6.17% / 34.01% | 9.05% / 55.55% |
| K10 data(comparison) median | 1 | b only | 4.01% / 22.98% | 6.10% / 33.93% | 8.98% / 55.30% |
| K10 data(comparison) median | 1 | a_A only | 4.09% / 23.06% | 6.18% / 34.02% | 9.07% / 55.55% |
| K10 data(comparison) median | 1 | N | 4.02% / 22.98% | 6.11% / 33.93% | 8.99% / 55.30% |
| K10 data(comparison) median | 1 | S | 21.04% / 28.79% | 23.13% / 36.11% | 26.01% / 55.44% |
| K10 data(comparison) median | 1 | S-d | 15.87% / 24.44% | 17.96% / 35.39% | 20.84% / 55.40% |
| K10 data(comparison) median | 1 | S-120 | 10.22% / 23.72% | 12.31% / 34.67% | 15.20% / 55.35% |
| K10 data(comparison) quiet | 0.2 | OLD | 5.12% / 16.26% | 7.01% / 24.64% | 10.18% / 41.18% |
| K10 data(comparison) quiet | 0.2 | b only | 5.06% / 16.17% | 6.96% / 24.55% | 10.12% / 41.10% |
| K10 data(comparison) quiet | 0.2 | a_A only | 5.17% / 16.26% | 7.07% / 24.65% | 10.23% / 41.19% |
| K10 data(comparison) quiet | 0.2 | N | 5.11% / 16.18% | 7.01% / 24.56% | 10.17% / 41.11% |
| K10 data(comparison) quiet | 0.2 | S | 49.36% / 40.88% | 51.26% / 72.78% | 54.42% / 66.41% |
| K10 data(comparison) quiet | 0.2 | S-d | 39.78% / 40.35% | 41.68% / 61.72% | 44.84% / 65.88% |
| K10 data(comparison) quiet | 0.2 | S-120 | 25.79% / 38.42% | 27.69% / 39.95% | 30.85% / 44.16% |
| K10 data(comparison) quiet | 1 | OLD | 3.85% / 15.60% | 5.65% / 23.84% | 8.91% / 40.52% |
| K10 data(comparison) quiet | 1 | b only | 3.78% / 15.51% | 5.58% / 23.75% | 8.84% / 40.43% |
| K10 data(comparison) quiet | 1 | a_A only | 3.86% / 15.60% | 5.67% / 23.84% | 8.92% / 40.52% |
| K10 data(comparison) quiet | 1 | N | 3.79% / 15.51% | 5.59% / 23.75% | 8.85% / 40.44% |
| K10 data(comparison) quiet | 1 | S | 19.13% / 26.87% | 20.94% / 28.27% | 24.19% / 42.34% |
| K10 data(comparison) quiet | 1 | S-d | 14.43% / 19.81% | 16.23% / 25.03% | 19.49% / 41.71% |
| K10 data(comparison) quiet | 1 | S-120 | 9.34% / 16.16% | 11.14% / 24.40% | 14.40% / 41.08% |

S OneSource without T01t(sensitivity; lower pooled / median):

| window | V | S lower | S upper | N lower(same set) |
|---|---|---|---|---|
| busy | 0.2 | 86.04% / 87.80% | 87.92% / 89.06% | 6.65% / 22.70% |
| busy | 1 | 34.21% / 34.45% | 35.96% / 42.25% | 3.80% / 22.08% |
| median | 0.2 | 77.13% / 77.05% | 78.95% / 78.70% | 5.74% / 46.09% |
| median | 1 | 28.99% / 46.38% | 30.69% / 69.25% | 3.62% / 46.27% |
| quiet | 0.2 | 74.93% / 74.76% | 76.69% / 100.66% | 6.08% / 66.61% |
| quiet | 1 | 27.13% / 66.53% | 28.76% / 100.17% | 4.04% / 66.42% |

## 5. V grid set total (lower pooled / median; upper pooled / median)

| set | mode | V 0.2 | V 0.5 | V 1 | V 2 | V 5 |
|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | N | 7.00% / 23.31%; 8.99% / 36.52% | 4.85% / 21.04%; 6.72% / 33.71% | 4.10% / 20.28%; 5.93% / 33.09% | 3.72% / 19.92%; 5.53% / 33.10% | 3.50% / 20.03%; 5.30% / 33.35% |
| classified data seller tier 0/1 endpoint revenue busy | S | 84.75% / 58.04%; 86.71% / 68.21% | 54.69% / 40.43%; 56.55% / 50.50% | 33.89% / 28.87%; 35.72% / 38.91% | 20.11% / 21.32%; 21.92% / 33.50% | 10.50% / 20.25%; 12.30% / 33.57% |
| classified data seller tier 0/1 endpoint revenue median | N | 7.34% / 42.71%; 9.88% / 63.61% | 5.66% / 42.48%; 8.05% / 63.28% | 4.99% / 42.66%; 7.33% / 63.43% | 4.66% / 43.23%; 6.97% / 63.98% | 4.46% / 45.10%; 6.76% / 65.83% |
| classified data seller tier 0/1 endpoint revenue median | S | 74.24% / 61.66%; 76.68% / 73.98% | 46.84% / 47.08%; 49.19% / 63.44% | 28.73% / 42.79%; 31.05% / 63.56% | 17.47% / 43.34%; 19.78% / 64.09% | 9.88% / 45.20%; 12.17% / 65.94% |
| classified data seller tier 0/1 endpoint revenue quiet | N | 7.12% / 66.11%; 9.40% / 99.83% | 5.48% / 66.01%; 7.61% / 99.63% | 4.85% / 66.41%; 6.93% / 99.99% | 4.55% / 67.41%; 6.60% / 100.98% | 4.37% / 70.59%; 6.40% / 104.14% |
| classified data seller tier 0/1 endpoint revenue quiet | S | 71.70% / 70.82%; 73.89% / 100.04% | 43.53% / 66.16%; 45.62% / 99.77% | 26.51% / 66.53%; 28.56% / 100.12% | 16.15% / 67.52%; 18.19% / 101.09% | 9.26% / 70.69%; 11.29% / 104.25% |
| D94 | N | 8.18% / 31.01%; 8.43% / 53.51% | 7.95% / 30.61%; 8.19% / 53.23% | 7.77% / 30.51%; 8.01% / 53.33% | 5.67% / 30.53%; 5.91% / 53.80% | 4.40% / 30.73%; 4.63% / 55.35% |
| D94 | S | 94.80% / 42.42%; 95.05% / 72.07% | 93.54% / 41.60%; 93.78% / 66.48% | 92.29% / 38.56%; 92.53% / 62.77% | 88.57% / 38.53%; 88.80% / 62.82% | 82.67% / 38.33%; 82.91% / 63.34% |
| BlockRun(tier 1b) busy | N | 93.81% / 93.81%; 93.99% / 93.99% | 63.76% / 63.76%; 63.85% / 63.85% | 40.72% / 40.72%; 40.77% / 40.77% | 24.62% / 24.62%; 24.66% / 24.66% | 13.02% / 13.02%; 13.05% / 13.05% |
| BlockRun(tier 1b) busy | S | 104.92% / 104.92%; 105.10% / 105.10% | 104.65% / 104.65%; 104.74% / 104.74% | 104.56% / 104.56%; 104.61% / 104.61% | 104.51% / 104.51%; 104.55% / 104.55% | 104.09% / 104.09%; 104.12% / 104.12% |
| BlockRun(tier 1b) median | N | 77.74% / 77.74%; 77.84% / 77.84% | 50.56% / 50.56%; 50.62% / 50.62% | 33.22% / 33.22%; 33.26% / 33.26% | 21.77% / 21.77%; 21.80% / 21.80% | 10.92% / 10.92%; 10.95% / 10.95% |
| BlockRun(tier 1b) median | S | 101.63% / 101.63%; 101.74% / 101.74% | 101.52% / 101.52%; 101.58% / 101.58% | 101.48% / 101.48%; 101.52% / 101.52% | 101.48% / 101.48%; 101.51% / 101.51% | 101.26% / 101.26%; 101.28% / 101.28% |
| BlockRun(tier 1b) quiet | N | 4.53% / 4.53%; 4.94% / 4.94% | 3.46% / 3.46%; 3.85% / 3.85% | 2.52% / 2.52%; 2.89% / 2.89% | 1.84% / 1.84%; 2.19% / 2.19% | 1.30% / 1.30%; 1.65% / 1.65% |
| BlockRun(tier 1b) quiet | S | 89.82% / 89.82%; 90.22% / 90.22% | 78.99% / 78.99%; 79.38% / 79.38% | 61.73% / 61.73%; 62.10% / 62.10% | 41.78% / 41.78%; 42.14% / 42.14% | 19.92% / 19.92%; 20.27% / 20.27% |

## 6. cost optimum (V, k) and its point retention payment (σ 1, w 0.00173, facilitator none)

L = b + R/W_b × H(k) (a 0, USDC). "revenue relative to" window revenue R for L, "days" L one day mean revenue divided value. same if totals small V, then small k. V 0.2b 5if grid is the end.

| window | seller | case | mode | V* | k* | total | same k V 1 total | b | R/W_b × H(k*) | L USDC | L / R | L days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 2.49% | 3.10% | 5.00 | 21.4703 | 26.4703 | 1.81% | 0.38 |
| busy | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 9.85% | 34.45% | 5.00 | 276.1031 | 281.1031 | 19.27% | 4.05 |
| busy | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 3.59% | 4.22% | 5.00 | 6.5146 | 11.5146 | 0.79% | 0.17 |
| busy | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 10.95% | 35.58% | 5.00 | 261.1474 | 266.1474 | 18.24% | 3.83 |
| busy | OneSource | lower | N | 5 (grid end) | 32 | 17.47% | 18.49% | 5.00 | 0.4548 | 5.4548 | 17.65% | 3.71 |
| busy | OneSource | lower | S | 5 (grid end) | 32 | 17.49% | 18.18% | 5.00 | 5.8491 | 10.8491 | 35.10% | 7.37 |
| busy | OneSource | upper | N | 5 (grid end) | 1 | 23.25% | 24.53% | 5.00 | 0.1380 | 5.1380 | 16.62% | 3.49 |
| busy | OneSource | upper | S | 5 (grid end) | 1 | 23.21% | 23.92% | 5.00 | 5.5322 | 10.5322 | 34.08% | 7.16 |
| busy | CoinMarketCap | lower | N | 5 (grid end) | 32 | 22.00% | 22.08% | 5.00 | 0.6419 | 5.6419 | 12.93% | 2.72 |
| busy | CoinMarketCap | lower | S | 5 (grid end) | 32 | 22.33% | 23.30% | 5.00 | 8.2552 | 13.2552 | 30.39% | 6.38 |
| busy | CoinMarketCap | upper | N | 5 (grid end) | 1 | 40.92% | 41.02% | 5.00 | 0.1948 | 5.1948 | 11.91% | 2.50 |
| busy | CoinMarketCap | upper | S | 5 (grid end) | 1 | 41.25% | 42.25% | 5.00 | 7.8081 | 12.8081 | 29.36% | 6.17 |
| busy | StableApify | lower | N | 1 | 1 | 17.40% | 17.40% | 1.00 | 0.0134 | 1.0134 | 33.84% | 7.11 |
| busy | StableApify | lower | S | 1 | 1 | 17.58% | 17.58% | 1.00 | 0.5361 | 1.5361 | 51.29% | 10.77 |
| busy | StableApify | upper | N | 1 | 1 | 25.15% | 25.15% | 1.00 | 0.0134 | 1.0134 | 33.84% | 7.11 |
| busy | StableApify | upper | S | 1 | 1 | 25.33% | 25.33% | 1.00 | 0.5361 | 1.5361 | 51.29% | 10.77 |
| busy | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 719.33% | 720.74% | 0.20 | 0.0035 | 0.2035 | 86.58% | 18.18 |
| busy | Exa(0.001 or less) | lower | S | 0.2 (grid end) | 32 | 719.46% | 720.84% | 0.20 | 0.0445 | 0.2445 | 104.03% | 21.85 |
| busy | Exa(0.001 or less) | upper | N | 0.2 (grid end) | 1 | 1268.64% | 1269.90% | 0.20 | 0.0010 | 0.2010 | 85.55% | 17.97 |
| busy | Exa(0.001 or less) | upper | S | 0.2 (grid end) | 1 | 1268.77% | 1270.01% | 0.20 | 0.0421 | 0.2421 | 103.01% | 21.63 |
| busy | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 264.19% | 270.61% | 0.20 | 0.0003 | 0.2003 | 303.48% | 63.73 |
| busy | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 264.30% | 270.71% | 0.20 | 0.0118 | 0.2118 | 320.93% | 67.40 |
| busy | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 394.03% | 400.31% | 0.20 | 0.0003 | 0.2003 | 303.48% | 63.73 |
| busy | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 394.14% | 400.41% | 0.20 | 0.0118 | 0.2118 | 320.93% | 67.40 |
| busy | BlockRun | lower | N | 5 (grid end) | 4 | 13.02% | 40.72% | 5.00 | 574.8772 | 579.8772 | 0.55% | 0.12 |
| busy | BlockRun | lower | S | 5 (grid end) | 4 | 104.09% | 104.56% | 5.00 | 18960.2660 | 18965.2660 | 18.00% | 3.78 |
| busy | BlockRun | upper | N | 5 (grid end) | 1 | 13.05% | 40.77% | 5.00 | 470.3752 | 475.3752 | 0.45% | 0.09 |
| busy | BlockRun | upper | S | 5 (grid end) | 1 | 104.12% | 104.61% | 5.00 | 18855.7640 | 18860.7640 | 17.90% | 3.76 |
| median | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 2.87% | 3.37% | 5.00 | 16.6984 | 21.6984 | 1.91% | 0.40 |
| median | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 8.67% | 28.79% | 5.00 | 214.7382 | 219.7382 | 19.37% | 4.07 |
| median | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 4.38% | 4.90% | 5.00 | 5.0667 | 10.0667 | 0.89% | 0.19 |
| median | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 10.18% | 30.33% | 5.00 | 203.1065 | 208.1065 | 18.34% | 3.85 |
| median | OneSource | lower | N | 5 (grid end) | 32 | 23.11% | 24.19% | 5.00 | 1.1953 | 6.1953 | 7.63% | 1.60 |
| median | OneSource | lower | S | 5 (grid end) | 32 | 23.39% | 25.16% | 5.00 | 15.3718 | 20.3718 | 25.08% | 5.27 |
| median | OneSource | upper | N | 5 (grid end) | 1 | 34.09% | 35.43% | 5.00 | 0.3627 | 5.3627 | 6.60% | 1.39 |
| median | OneSource | upper | S | 5 (grid end) | 1 | 34.31% | 36.11% | 5.00 | 14.5391 | 19.5391 | 24.06% | 5.05 |
| median | CoinMarketCap | lower | N | 0.5 | 1 | 39.02% | 39.06% | 0.50 | 0.0073 | 0.5073 | 31.12% | 6.54 |
| median | CoinMarketCap | lower | S | 1 | 1 | 39.20% | 39.20% | 1.00 | 0.2918 | 1.2918 | 79.25% | 16.64 |
| median | CoinMarketCap | upper | N | 0.5 | 1 | 57.72% | 57.72% | 0.50 | 0.0073 | 0.5073 | 31.12% | 6.54 |
| median | CoinMarketCap | upper | S | 1 | 1 | 57.86% | 57.86% | 1.00 | 0.2918 | 1.2918 | 79.25% | 16.64 |
| median | StableApify | lower | N | 0.5 | 1 | 45.94% | 46.27% | 0.50 | 0.0028 | 0.5028 | 80.45% | 16.89 |
| median | StableApify | lower | S | 0.5 | 1 | 46.08% | 46.38% | 0.50 | 0.1119 | 0.6119 | 97.90% | 20.56 |
| median | StableApify | upper | N | 0.5 | 1 | 68.84% | 69.13% | 0.50 | 0.0028 | 0.5028 | 80.45% | 16.89 |
| median | StableApify | upper | S | 0.5 | 1 | 68.98% | 69.25% | 0.50 | 0.1119 | 0.6119 | 97.90% | 20.56 |
| median | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 701.99% | 703.16% | 0.20 | 0.0039 | 0.2039 | 76.38% | 16.04 |
| median | Exa(0.001 or less) | lower | S | 0.2 (grid end) | 32 | 702.13% | 703.27% | 0.20 | 0.0505 | 0.2505 | 93.83% | 19.70 |
| median | Exa(0.001 or less) | upper | N | 0.2 (grid end) | 1 | 1259.89% | 1260.92% | 0.20 | 0.0012 | 0.2012 | 75.35% | 15.82 |
| median | Exa(0.001 or less) | upper | S | 0.2 (grid end) | 1 | 1260.03% | 1261.03% | 0.20 | 0.0478 | 0.2478 | 92.81% | 19.49 |
| median | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 424.14% | 440.03% | 0.20 | 0.0001 | 0.2001 | 714.73% | 150.09 |
| median | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 424.25% | 440.13% | 0.20 | 0.0050 | 0.2050 | 732.19% | 153.76 |
| median | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 637.24% | 652.98% | 0.20 | 0.0001 | 0.2001 | 714.73% | 150.09 |
| median | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 637.34% | 653.09% | 0.20 | 0.0050 | 0.2050 | 732.19% | 153.76 |
| median | BlockRun | lower | N | 5 (grid end) | 4 | 10.92% | 33.22% | 5.00 | 698.0116 | 703.0116 | 0.55% | 0.12 |
| median | BlockRun | lower | S | 5 (grid end) | 4 | 101.26% | 101.48% | 5.00 | 23021.4137 | 23026.4137 | 18.00% | 3.78 |
| median | BlockRun | upper | N | 5 (grid end) | 1 | 10.95% | 33.26% | 5.00 | 571.1261 | 576.1261 | 0.45% | 0.09 |
| median | BlockRun | upper | S | 5 (grid end) | 1 | 101.28% | 101.52% | 5.00 | 22894.5281 | 22899.5281 | 17.90% | 3.76 |
| quiet | StableEnrich(Out candidates excluded) | lower | N | 5 (grid end) | 32 | 3.27% | 3.73% | 5.00 | 14.9670 | 19.9670 | 2.75% | 0.41 |
| quiet | StableEnrich(Out candidates excluded) | lower | S | 5 (grid end) | 32 | 8.49% | 26.87% | 5.00 | 192.4718 | 197.4718 | 27.18% | 4.08 |
| quiet | StableEnrich(Out candidates excluded) | upper | N | 5 (grid end) | 1 | 4.65% | 5.13% | 5.00 | 4.5413 | 9.5413 | 1.31% | 0.20 |
| quiet | StableEnrich(Out candidates excluded) | upper | S | 5 (grid end) | 1 | 9.87% | 28.27% | 5.00 | 182.0462 | 187.0462 | 25.75% | 3.86 |
| quiet | OneSource | lower | N | 5 (grid end) | 32 | 15.65% | 16.72% | 5.00 | 1.0359 | 6.0359 | 12.00% | 1.80 |
| quiet | OneSource | lower | S | 5 (grid end) | 32 | 15.87% | 17.42% | 5.00 | 13.3217 | 18.3217 | 36.44% | 5.47 |
| quiet | OneSource | upper | N | 5 (grid end) | 1 | 23.92% | 25.25% | 5.00 | 0.3143 | 5.3143 | 10.57% | 1.59 |
| quiet | OneSource | upper | S | 5 (grid end) | 1 | 24.09% | 25.66% | 5.00 | 12.6001 | 17.6001 | 35.00% | 5.25 |
| quiet | CoinMarketCap | lower | N | 0.5 | 1 | 66.32% | 66.40% | 0.50 | 0.0059 | 0.5059 | 53.26% | 7.99 |
| quiet | CoinMarketCap | lower | S | 0.5 | 1 | 66.49% | 66.53% | 0.50 | 0.2381 | 0.7381 | 77.69% | 11.65 |
| quiet | CoinMarketCap | upper | N | 0.5 | 1 | 99.99% | 100.03% | 0.50 | 0.0059 | 0.5059 | 53.26% | 7.99 |
| quiet | CoinMarketCap | upper | S | 0.5 | 1 | 100.16% | 100.17% | 0.50 | 0.2381 | 0.7381 | 77.69% | 11.65 |
| quiet | StableApify | lower | N | 0.2 (grid end) | 1 | 65.61% | 66.42% | 0.20 | 0.0015 | 0.2015 | 83.96% | 12.59 |
| quiet | StableApify | lower | S | 0.2 (grid end) | 1 | 65.75% | 66.53% | 0.20 | 0.0601 | 0.2601 | 108.39% | 16.26 |
| quiet | StableApify | upper | N | 0.5 | 1 | 99.27% | 99.95% | 0.50 | 0.0015 | 0.5015 | 208.96% | 31.34 |
| quiet | StableApify | upper | S | 0.5 | 1 | 99.39% | 100.06% | 0.50 | 0.0601 | 0.5601 | 233.39% | 35.01 |
| quiet | Exa(0.001 or less) | lower | N | 0.2 (grid end) | 32 | 828.36% | 829.65% | 0.20 | 0.0037 | 0.2037 | 114.42% | 17.16 |
| quiet | Exa(0.001 or less) | lower | S | 0.2 (grid end) | 32 | 828.49% | 829.76% | 0.20 | 0.0472 | 0.2472 | 138.86% | 20.83 |
| quiet | Exa(0.001 or less) | upper | N | 0.2 (grid end) | 1 | 1519.40% | 1520.56% | 0.20 | 0.0011 | 0.2011 | 112.98% | 16.95 |
| quiet | Exa(0.001 or less) | upper | S | 0.2 (grid end) | 1 | 1519.54% | 1520.66% | 0.20 | 0.0446 | 0.2446 | 137.42% | 20.61 |
| quiet | CoinStats(0.01 or less) | lower | N | 0.2 (grid end) | 1 | 313.12% | 342.45% | 0.20 | 0.0001 | 0.2001 | 1818.81% | 272.82 |
| quiet | CoinStats(0.01 or less) | lower | S | 0.2 (grid end) | 1 | 313.23% | 342.56% | 0.20 | 0.0028 | 0.2028 | 1843.24% | 276.49 |
| quiet | CoinStats(0.01 or less) | upper | N | 0.2 (grid end) | 1 | 477.67% | 506.86% | 0.20 | 0.0001 | 0.2001 | 1818.81% | 272.82 |
| quiet | CoinStats(0.01 or less) | upper | S | 0.2 (grid end) | 1 | 477.77% | 506.96% | 0.20 | 0.0028 | 0.2028 | 1843.24% | 276.49 |
| quiet | BlockRun | lower | N | 5 (grid end) | 32 | 1.30% | 2.52% | 5.00 | 58.4451 | 63.4451 | 2.24% | 0.34 |
| quiet | BlockRun | lower | S | 5 (grid end) | 32 | 19.92% | 61.73% | 5.00 | 751.5918 | 756.5918 | 26.67% | 4.00 |
| quiet | BlockRun | upper | N | 5 (grid end) | 1 | 1.65% | 2.89% | 5.00 | 17.7336 | 22.7336 | 0.80% | 0.12 |
| quiet | BlockRun | upper | S | 5 (grid end) | 1 | 20.27% | 62.10% | 5.00 | 710.8803 | 715.8803 | 25.24% | 3.79 |

set optimal V (all seller same V, per seller k; lower pooled most small V) and then retention payment sum:

| set | mode | V* | lower pooled | median | Σb | Σ R/W_b H(k) | ΣL USDC | ΣL / ΣR |
|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | N | 5 | 3.50% | 20.03% | 30.00 | 22.58 | 52.58 | 3.42% |
| classified data seller tier 0/1 endpoint revenue busy | S | 5 | 10.50% | 20.25% | 30.00 | 290.80 | 320.80 | 20.88% |
| classified data seller tier 0/1 endpoint revenue median | N | 5 | 4.46% | 45.10% | 30.00 | 17.91 | 47.91 | 3.93% |
| classified data seller tier 0/1 endpoint revenue median | S | 5 | 9.88% | 45.20% | 30.00 | 230.57 | 260.57 | 21.39% |
| classified data seller tier 0/1 endpoint revenue quiet | N | 5 | 4.37% | 70.59% | 30.00 | 16.01 | 46.01 | 5.91% |
| classified data seller tier 0/1 endpoint revenue quiet | S | 5 | 9.26% | 70.69% | 30.00 | 206.14 | 236.14 | 30.35% |
| D94 | N | 5 | 4.40% | 30.73% | 470.00 | 792.30 | 1262.30 | 1.24% |
| D94 | S | 5 | 82.67% | 38.33% | 470.00 | 18554.42 | 19024.42 | 18.69% |

## 7. K10h(old value) with difference (lower and upper, facilitator none; difference %p)

K10h columns k10h_output.md value(1in section OLD and equality check). bonly deduction only V, a_Aonly a_A only 120 changed value.

| window | V | seller | case | K10h | b only | a_A only | N | S | N − K10h | S − K10h | S − N | K10h k | N k | S k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | 0.2 | StableEnrich(Out candidates excluded) | lower | 5.97% | 5.89% | 6.11% | 6.02% | 87.80% | +0.05 | +81.82 | +81.77 | 32 | 32 | 32 |
| busy | 0.2 | StableEnrich(Out candidates excluded) | upper | 7.23% | 7.15% | 7.37% | 7.28% | 89.06% | +0.05 | +81.82 | +81.77 | 1 | 1 | 1 |
| busy | 0.2 | OneSource | lower | 24.01% | 23.92% | 24.01% | 23.93% | 21.89% | -0.08 | -2.12 | -2.04 | 32 | 32 | 32 |
| busy | 0.2 | OneSource | upper | 31.33% | 31.25% | 31.34% | 31.25% | 27.78% | -0.08 | -3.56 | -3.48 | 1 | 1 | 1 |
| busy | 0.2 | CoinMarketCap | lower | 22.78% | 22.69% | 22.78% | 22.70% | 28.28% | -0.08 | +5.50 | +5.58 | 32 | 32 | 32 |
| busy | 0.2 | CoinMarketCap | upper | 41.86% | 41.78% | 41.87% | 41.78% | 47.37% | -0.08 | +5.50 | +5.58 | 1 | 1 | 1 |
| busy | 0.2 | StableApify | lower | 17.91% | 17.81% | 17.91% | 17.81% | 18.30% | -0.10 | +0.39 | +0.49 | 1 | 1 | 1 |
| busy | 0.2 | StableApify | upper | 25.80% | 25.69% | 25.80% | 25.69% | 26.18% | -0.10 | +0.39 | +0.49 | 1 | 1 | 1 |
| busy | 0.2 | Exa(0.001 or less) | lower | 719.65% | 719.33% | 719.65% | 719.33% | 719.46% | -0.32 | -0.19 | +0.13 | 32 | 32 | 32 |
| busy | 0.2 | Exa(0.001 or less) | upper | 1268.96% | 1268.64% | 1268.96% | 1268.64% | 1268.77% | -0.32 | -0.19 | +0.13 | 1 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | lower | 265.11% | 264.19% | 265.11% | 264.19% | 264.30% | -0.92 | -0.81 | +0.11 | 1 | 1 | 1 |
| busy | 0.2 | CoinStats(0.01 or less) | upper | 394.95% | 394.03% | 394.95% | 394.03% | 394.14% | -0.92 | -0.81 | +0.11 | 1 | 1 | 1 |
| busy | 0.2 | BlockRun | lower | 92.75% | 92.67% | 93.89% | 93.81% | 104.92% | +1.05 | +12.16 | +11.11 | 4 | 4 | 4 |
| busy | 0.2 | BlockRun | upper | 92.94% | 92.86% | 94.07% | 93.99% | 105.10% | +1.05 | +12.16 | +11.11 | 1 | 1 | 1 |
| busy | 1 | StableEnrich(Out candidates excluded) | lower | 3.15% | 3.07% | 3.18% | 3.10% | 34.45% | -0.06 | +31.30 | +31.35 | 32 | 32 | 32 |
| busy | 1 | StableEnrich(Out candidates excluded) | upper | 4.28% | 4.20% | 4.31% | 4.22% | 35.58% | -0.06 | +31.30 | +31.35 | 1 | 1 | 1 |
| busy | 1 | OneSource | lower | 18.58% | 18.49% | 18.58% | 18.49% | 18.18% | -0.09 | -0.41 | -0.31 | 32 | 32 | 32 |
| busy | 1 | OneSource | upper | 24.62% | 24.52% | 24.62% | 24.53% | 23.92% | -0.09 | -0.69 | -0.60 | 1 | 1 | 1 |
| busy | 1 | CoinMarketCap | lower | 22.17% | 22.08% | 22.17% | 22.08% | 23.30% | -0.09 | +1.13 | +1.22 | 32 | 32 | 32 |
| busy | 1 | CoinMarketCap | upper | 41.11% | 41.02% | 41.11% | 41.02% | 42.25% | -0.09 | +1.13 | +1.22 | 1 | 1 | 1 |
| busy | 1 | StableApify | lower | 17.58% | 17.40% | 17.58% | 17.40% | 17.58% | -0.18 | +0.00 | +0.18 | 1 | 1 | 1 |
| busy | 1 | StableApify | upper | 25.32% | 25.15% | 25.32% | 25.15% | 25.33% | -0.18 | +0.00 | +0.18 | 1 | 1 | 1 |
| busy | 1 | Exa(0.001 or less) | lower | 722.00% | 720.74% | 722.00% | 720.74% | 720.84% | -1.26 | -1.16 | +0.11 | 32 | 32 | 32 |
| busy | 1 | Exa(0.001 or less) | upper | 1271.17% | 1269.90% | 1271.17% | 1269.90% | 1270.01% | -1.26 | -1.16 | +0.11 | 1 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | lower | 274.89% | 270.61% | 274.89% | 270.61% | 270.71% | -4.28 | -4.18 | +0.10 | 1 | 1 | 1 |
| busy | 1 | CoinStats(0.01 or less) | upper | 404.59% | 400.31% | 404.59% | 400.31% | 400.41% | -4.28 | -4.18 | +0.10 | 1 | 1 | 1 |
| busy | 1 | BlockRun | lower | 39.51% | 39.43% | 40.80% | 40.72% | 104.56% | +1.21 | +65.04 | +63.84 | 4 | 4 | 4 |
| busy | 1 | BlockRun | upper | 39.57% | 39.48% | 40.85% | 40.77% | 104.61% | +1.21 | +65.04 | +63.84 | 1 | 1 | 1 |
| median | 0.2 | StableEnrich(Out candidates excluded) | lower | 5.48% | 5.40% | 5.57% | 5.50% | 77.05% | +0.02 | +71.57 | +71.55 | 32 | 32 | 32 |
| median | 0.2 | StableEnrich(Out candidates excluded) | upper | 7.13% | 7.05% | 7.22% | 7.15% | 78.70% | +0.02 | +71.57 | +71.55 | 1 | 1 | 1 |
| median | 0.2 | OneSource | lower | 29.80% | 29.71% | 29.80% | 29.72% | 33.73% | -0.08 | +3.93 | +4.01 | 32 | 32 | 32 |
| median | 0.2 | OneSource | upper | 42.33% | 42.24% | 42.33% | 42.25% | 44.82% | -0.08 | +2.49 | +2.57 | 1 | 1 | 1 |
| median | 0.2 | CoinMarketCap | lower | 39.45% | 39.33% | 39.45% | 39.33% | 39.65% | -0.12 | +0.19 | +0.31 | 1 | 1 | 1 |
| median | 0.2 | CoinMarketCap | upper | 58.25% | 58.14% | 58.25% | 58.14% | 58.45% | -0.12 | +0.19 | +0.31 | 1 | 1 | 1 |
| median | 0.2 | StableApify | lower | 46.26% | 46.09% | 46.26% | 46.09% | 46.27% | -0.17 | +0.01 | +0.18 | 1 | 1 | 1 |
| median | 0.2 | StableApify | upper | 69.26% | 69.09% | 69.26% | 69.09% | 69.27% | -0.17 | +0.01 | +0.18 | 1 | 1 | 1 |
| median | 0.2 | Exa(0.001 or less) | lower | 702.28% | 701.99% | 702.28% | 701.99% | 702.13% | -0.29 | -0.16 | +0.13 | 32 | 32 | 32 |
| median | 0.2 | Exa(0.001 or less) | upper | 1260.18% | 1259.89% | 1260.18% | 1259.89% | 1260.03% | -0.29 | -0.16 | +0.13 | 1 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | lower | 426.21% | 424.14% | 426.21% | 424.14% | 424.25% | -2.06 | -1.96 | +0.10 | 1 | 1 | 1 |
| median | 0.2 | CoinStats(0.01 or less) | upper | 639.30% | 637.24% | 639.30% | 637.24% | 637.34% | -2.06 | -1.96 | +0.10 | 1 | 1 | 1 |
| median | 0.2 | BlockRun | lower | 76.21% | 76.17% | 77.78% | 77.74% | 101.63% | +1.52 | +25.42 | +23.90 | 4 | 4 | 4 |
| median | 0.2 | BlockRun | upper | 76.32% | 76.27% | 77.89% | 77.84% | 101.74% | +1.52 | +25.42 | +23.90 | 1 | 1 | 1 |
| median | 1 | StableEnrich(Out candidates excluded) | lower | 3.43% | 3.35% | 3.45% | 3.37% | 28.79% | -0.06 | +25.36 | +25.42 | 32 | 32 | 32 |
| median | 1 | StableEnrich(Out candidates excluded) | upper | 4.96% | 4.88% | 4.99% | 4.90% | 30.33% | -0.06 | +25.36 | +25.42 | 1 | 1 | 1 |
| median | 1 | OneSource | lower | 24.27% | 24.19% | 24.27% | 24.19% | 25.16% | -0.09 | +0.88 | +0.97 | 32 | 32 | 32 |
| median | 1 | OneSource | upper | 35.51% | 35.43% | 35.51% | 35.43% | 36.11% | -0.09 | +0.60 | +0.68 | 1 | 1 | 1 |
| median | 1 | CoinMarketCap | lower | 39.31% | 39.06% | 39.31% | 39.06% | 39.20% | -0.25 | -0.11 | +0.14 | 1 | 1 | 1 |
| median | 1 | CoinMarketCap | upper | 57.98% | 57.72% | 57.98% | 57.72% | 57.86% | -0.25 | -0.11 | +0.14 | 1 | 1 | 1 |
| median | 1 | StableApify | lower | 46.79% | 46.27% | 46.79% | 46.27% | 46.38% | -0.53 | -0.41 | +0.12 | 1 | 1 | 1 |
| median | 1 | StableApify | upper | 69.66% | 69.13% | 69.66% | 69.13% | 69.25% | -0.53 | -0.41 | +0.12 | 1 | 1 | 1 |
| median | 1 | Exa(0.001 or less) | lower | 704.28% | 703.16% | 704.28% | 703.16% | 703.27% | -1.12 | -1.01 | +0.11 | 32 | 32 | 32 |
| median | 1 | Exa(0.001 or less) | upper | 1262.04% | 1260.92% | 1262.04% | 1260.92% | 1261.03% | -1.12 | -1.01 | +0.11 | 1 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | lower | 450.00% | 440.03% | 450.00% | 440.03% | 440.13% | -9.98 | -9.88 | +0.10 | 1 | 1 | 1 |
| median | 1 | CoinStats(0.01 or less) | upper | 662.96% | 652.98% | 662.96% | 652.98% | 653.09% | -9.98 | -9.88 | +0.10 | 1 | 1 | 1 |
| median | 1 | BlockRun | lower | 32.11% | 32.05% | 33.28% | 33.22% | 101.48% | +1.11 | +69.37 | +68.26 | 4 | 4 | 4 |
| median | 1 | BlockRun | upper | 32.15% | 32.09% | 33.32% | 33.26% | 101.52% | +1.11 | +69.37 | +68.26 | 1 | 1 | 1 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | lower | 5.76% | 5.68% | 5.85% | 5.77% | 74.76% | +0.01 | +69.00 | +68.99 | 32 | 32 | 32 |
| quiet | 0.2 | StableEnrich(Out candidates excluded) | upper | 7.29% | 7.21% | 7.38% | 7.30% | 76.29% | +0.01 | +69.00 | +68.99 | 1 | 1 | 1 |
| quiet | 0.2 | OneSource | lower | 22.31% | 22.23% | 22.32% | 22.23% | 24.97% | -0.08 | +2.66 | +2.74 | 32 | 32 | 32 |
| quiet | 0.2 | OneSource | upper | 32.13% | 32.05% | 32.14% | 32.06% | 33.36% | -0.08 | +1.22 | +1.30 | 1 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | lower | 66.73% | 66.61% | 66.73% | 66.61% | 66.88% | -0.12 | +0.15 | +0.27 | 1 | 1 | 1 |
| quiet | 0.2 | CoinMarketCap | upper | 100.51% | 100.38% | 100.51% | 100.38% | 100.66% | -0.12 | +0.15 | +0.27 | 1 | 1 | 1 |
| quiet | 0.2 | StableApify | lower | 65.86% | 65.61% | 65.86% | 65.61% | 65.75% | -0.25 | -0.10 | +0.14 | 1 | 1 | 1 |
| quiet | 0.2 | StableApify | upper | 99.53% | 99.28% | 99.53% | 99.28% | 99.42% | -0.25 | -0.10 | +0.14 | 1 | 1 | 1 |
| quiet | 0.2 | Exa(0.001 or less) | lower | 828.67% | 828.36% | 828.67% | 828.36% | 828.49% | -0.31 | -0.17 | +0.13 | 32 | 32 | 32 |
| quiet | 0.2 | Exa(0.001 or less) | upper | 1519.71% | 1519.40% | 1519.71% | 1519.40% | 1519.54% | -0.31 | -0.17 | +0.13 | 1 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | lower | 316.80% | 313.12% | 316.80% | 313.12% | 313.23% | -3.68 | -3.58 | +0.10 | 1 | 1 | 1 |
| quiet | 0.2 | CoinStats(0.01 or less) | upper | 481.35% | 477.67% | 481.35% | 477.67% | 477.77% | -3.68 | -3.58 | +0.10 | 1 | 1 | 1 |
| quiet | 0.2 | BlockRun | lower | 4.41% | 4.38% | 4.56% | 4.53% | 89.82% | +0.12 | +85.40 | +85.29 | 32 | 32 | 32 |
| quiet | 0.2 | BlockRun | upper | 4.82% | 4.79% | 4.97% | 4.94% | 90.22% | +0.12 | +85.40 | +85.29 | 1 | 1 | 1 |
| quiet | 1 | StableEnrich(Out candidates excluded) | lower | 3.79% | 3.71% | 3.81% | 3.73% | 26.87% | -0.06 | +23.08 | +23.14 | 32 | 32 | 32 |
| quiet | 1 | StableEnrich(Out candidates excluded) | upper | 5.20% | 5.11% | 5.22% | 5.13% | 28.27% | -0.06 | +23.08 | +23.14 | 1 | 1 | 1 |
| quiet | 1 | OneSource | lower | 16.81% | 16.72% | 16.81% | 16.72% | 17.42% | -0.09 | +0.61 | +0.69 | 32 | 32 | 32 |
| quiet | 1 | OneSource | upper | 25.34% | 25.25% | 25.34% | 25.25% | 25.66% | -0.09 | +0.32 | +0.41 | 1 | 1 | 1 |
| quiet | 1 | CoinMarketCap | lower | 66.69% | 66.40% | 66.69% | 66.40% | 66.53% | -0.29 | -0.16 | +0.13 | 1 | 1 | 1 |
| quiet | 1 | CoinMarketCap | upper | 100.33% | 100.03% | 100.33% | 100.03% | 100.17% | -0.29 | -0.16 | +0.13 | 1 | 1 | 1 |
| quiet | 1 | StableApify | lower | 67.33% | 66.42% | 67.33% | 66.42% | 66.53% | -0.91 | -0.80 | +0.11 | 1 | 1 | 1 |
| quiet | 1 | StableApify | upper | 100.86% | 99.95% | 100.86% | 99.95% | 100.06% | -0.91 | -0.80 | +0.11 | 1 | 1 | 1 |
| quiet | 1 | Exa(0.001 or less) | lower | 830.85% | 829.65% | 830.85% | 829.65% | 829.76% | -1.19 | -1.09 | +0.11 | 32 | 32 | 32 |
| quiet | 1 | Exa(0.001 or less) | upper | 1521.75% | 1520.56% | 1521.75% | 1520.56% | 1520.66% | -1.19 | -1.09 | +0.11 | 1 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | lower | 360.53% | 342.45% | 360.53% | 342.45% | 342.56% | -18.07 | -17.97 | +0.10 | 1 | 1 | 1 |
| quiet | 1 | CoinStats(0.01 or less) | upper | 524.93% | 506.86% | 524.93% | 506.86% | 506.96% | -18.07 | -17.97 | +0.10 | 1 | 1 | 1 |
| quiet | 1 | BlockRun | lower | 2.52% | 2.45% | 2.59% | 2.52% | 61.73% | -0.01 | +59.21 | +59.21 | 32 | 32 | 32 |
| quiet | 1 | BlockRun | upper | 2.89% | 2.82% | 2.96% | 2.89% | 62.10% | -0.01 | +59.21 | +59.21 | 1 | 1 | 1 |

set (pooled / median):

| set | V | case | K10h | b only | a_A only | N | S | N − K10h pooled | S − K10h pooled | S − N pooled |
|---|---|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | 6.96% / 23.39% | 6.88% / 23.31% | 7.08% / 23.40% | 7.00% / 23.31% | 84.75% / 58.04% | +0.04 | +77.79 | +77.75 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | 8.95% / 36.60% | 8.87% / 36.51% | 9.07% / 36.60% | 8.99% / 36.52% | 86.71% / 68.21% | +0.04 | +77.76 | +77.72 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | 4.15% / 20.37% | 4.07% / 20.28% | 4.18% / 20.37% | 4.10% / 20.28% | 33.89% / 28.87% | -0.06 | +29.74 | +29.79 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | 5.99% / 33.22% | 5.90% / 33.09% | 6.01% / 33.22% | 5.93% / 33.09% | 35.72% / 38.91% | -0.06 | +29.73 | +29.79 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | 7.33% / 42.85% | 7.25% / 42.71% | 7.41% / 42.86% | 7.34% / 42.71% | 74.24% / 61.66% | +0.01 | +66.91 | +66.90 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | 9.86% / 63.76% | 9.79% / 63.61% | 9.95% / 63.76% | 9.88% / 63.61% | 76.68% / 73.98% | +0.01 | +66.82 | +66.80 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | 5.06% / 43.05% | 4.97% / 42.66% | 5.08% / 43.05% | 4.99% / 42.66% | 28.73% / 42.79% | -0.06 | +23.68 | +23.74 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | 7.39% / 63.82% | 7.31% / 63.43% | 7.41% / 63.82% | 7.33% / 63.43% | 31.05% / 63.56% | -0.06 | +23.66 | +23.72 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | 7.11% / 66.30% | 7.04% / 66.11% | 7.20% / 66.30% | 7.12% / 66.11% | 71.70% / 70.82% | +0.00 | +64.59 | +64.58 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | 9.39% / 100.02% | 9.31% / 99.83% | 9.47% / 100.02% | 9.40% / 99.83% | 73.89% / 100.04% | +0.00 | +64.50 | +64.49 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | 4.92% / 67.01% | 4.84% / 66.41% | 4.94% / 67.01% | 4.85% / 66.41% | 26.51% / 66.53% | -0.07 | +21.58 | +21.65 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | 7.00% / 100.59% | 6.91% / 99.99% | 7.02% / 100.59% | 6.93% / 99.99% | 28.56% / 100.12% | -0.07 | +21.57 | +21.63 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | lower | 22.98% / 22.78% | 22.90% / 22.69% | 22.99% / 22.78% | 22.90% / 22.70% | 27.65% / 28.28% | -0.08 | +4.66 | +4.74 |
| tier 0 and 1 data, StableEnrich excluded busy | 0.2 | upper | 38.09% / 41.86% | 38.00% / 41.78% | 38.10% / 41.87% | 38.01% / 41.78% | 42.75% / 47.37% | -0.08 | +4.66 | +4.74 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | lower | 22.41% / 22.17% | 22.31% / 22.08% | 22.41% / 22.17% | 22.31% / 22.08% | 23.36% / 23.30% | -0.10 | +0.95 | +1.05 |
| tier 0 and 1 data, StableEnrich excluded busy | 1 | upper | 37.38% / 41.11% | 37.28% / 41.02% | 37.38% / 41.11% | 37.28% / 41.02% | 38.33% / 42.25% | -0.10 | +0.95 | +1.05 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | lower | 26.51% / 46.26% | 26.43% / 46.09% | 26.52% / 46.26% | 26.43% / 46.09% | 36.20% / 46.27% | -0.08 | +9.68 | +9.76 |
| tier 0 and 1 data, StableEnrich excluded median | 0.2 | upper | 39.65% / 69.26% | 39.57% / 69.09% | 39.66% / 69.26% | 39.57% / 69.09% | 49.34% / 69.27% | -0.08 | +9.68 | +9.76 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | lower | 25.87% / 46.79% | 25.77% / 46.27% | 25.87% / 46.79% | 25.77% / 46.27% | 27.89% / 46.38% | -0.10 | +2.02 | +2.12 |
| tier 0 and 1 data, StableEnrich excluded median | 1 | upper | 38.87% / 69.66% | 38.77% / 69.13% | 38.87% / 69.66% | 38.77% / 69.13% | 40.89% / 69.25% | -0.10 | +2.02 | +2.12 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | lower | 20.28% / 66.73% | 20.19% / 66.61% | 20.29% / 66.73% | 20.20% / 66.61% | 28.76% / 66.88% | -0.08 | +8.48 | +8.57 |
| tier 0 and 1 data, StableEnrich excluded quiet | 0.2 | upper | 31.63% / 100.51% | 31.54% / 100.38% | 31.64% / 100.51% | 31.55% / 100.38% | 40.12% / 100.66% | -0.08 | +8.48 | +8.57 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | lower | 19.66% / 67.33% | 19.56% / 66.42% | 19.66% / 67.33% | 19.56% / 66.42% | 21.41% / 66.53% | -0.10 | +1.76 | +1.86 |
| tier 0 and 1 data, StableEnrich excluded quiet | 1 | upper | 30.87% / 100.86% | 30.77% / 100.03% | 30.87% / 100.86% | 30.77% / 100.03% | 32.63% / 100.17% | -0.10 | +1.76 | +1.86 |
| D94 | 0.2 | lower | 7.87% / 31.10% | 7.86% / 31.01% | 8.19% / 31.10% | 8.18% / 31.01% | 94.80% / 42.42% | +0.31 | +86.93 | +86.62 |
| D94 | 0.2 | upper | 8.12% / 53.64% | 8.11% / 53.51% | 8.44% / 53.64% | 8.43% / 53.51% | 95.05% / 72.07% | +0.31 | +86.93 | +86.62 |
| D94 | 1 | lower | 7.50% / 30.64% | 7.47% / 30.51% | 7.80% / 30.64% | 7.77% / 30.51% | 92.29% / 38.56% | +0.27 | +84.79 | +84.52 |
| D94 | 1 | upper | 7.74% / 53.68% | 7.71% / 53.33% | 8.04% / 53.68% | 8.01% / 53.33% | 92.53% / 62.77% | +0.27 | +84.79 | +84.52 |
| K10 data(comparison) busy | 0.2 | lower | 6.67% / 17.93% | 6.59% / 17.84% | 6.78% / 17.93% | 6.70% / 17.84% | 74.81% / 25.09% | +0.03 | +68.14 | +68.11 |
| K10 data(comparison) busy | 0.2 | upper | 8.98% / 25.41% | 8.91% / 25.31% | 9.09% / 25.41% | 9.02% / 25.32% | 77.12% / 39.81% | +0.03 | +68.14 | +68.11 |
| K10 data(comparison) busy | 1 | lower | 4.32% / 17.47% | 4.24% / 17.34% | 4.35% / 17.48% | 4.26% / 17.34% | 30.69% / 20.74% | -0.06 | +26.37 | +26.43 |
| K10 data(comparison) busy | 1 | upper | 6.52% / 24.78% | 6.44% / 24.65% | 6.54% / 24.78% | 6.46% / 24.65% | 32.89% / 30.74% | -0.06 | +26.37 | +26.43 |
| K10 data(comparison) median | 0.2 | lower | 5.39% / 23.74% | 5.33% / 23.66% | 5.45% / 23.75% | 5.39% / 23.67% | 51.82% / 39.65% | +0.00 | +46.42 | +46.42 |
| K10 data(comparison) median | 0.2 | upper | 7.57% / 34.83% | 7.51% / 34.75% | 7.63% / 34.84% | 7.57% / 34.76% | 54.00% / 58.45% | +0.00 | +46.42 | +46.42 |
| K10 data(comparison) median | 1 | lower | 4.08% / 23.06% | 4.01% / 22.98% | 4.09% / 23.06% | 4.02% / 22.98% | 21.04% / 28.79% | -0.06 | +16.96 | +17.02 |
| K10 data(comparison) median | 1 | upper | 6.17% / 34.01% | 6.10% / 33.93% | 6.18% / 34.02% | 6.11% / 33.93% | 23.13% / 36.11% | -0.06 | +16.96 | +17.02 |
| K10 data(comparison) quiet | 0.2 | lower | 5.12% / 16.26% | 5.06% / 16.17% | 5.17% / 16.26% | 5.11% / 16.18% | 49.36% / 40.88% | -0.00 | +44.24 | +44.24 |
| K10 data(comparison) quiet | 0.2 | upper | 7.01% / 24.64% | 6.96% / 24.55% | 7.07% / 24.65% | 7.01% / 24.56% | 51.26% / 72.78% | -0.00 | +44.24 | +44.24 |
| K10 data(comparison) quiet | 1 | lower | 3.85% / 15.60% | 3.78% / 15.51% | 3.86% / 15.60% | 3.79% / 15.51% | 19.13% / 26.87% | -0.06 | +15.29 | +15.34 |
| K10 data(comparison) quiet | 1 | upper | 5.65% / 23.84% | 5.58% / 23.75% | 5.67% / 23.84% | 5.59% / 23.75% | 20.94% / 28.27% | -0.06 | +15.29 | +15.34 |

## 8. 10% threshold w* (σ 1, facilitator none; lower / upper)

| set | statistics | mode | V 0.2 | V 1 |
|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | pooled | K10h | 0.00354 / 0.00235 | 0.0142 / 0.0103 |
| classified data seller tier 0/1 endpoint revenue busy | pooled | N | 0.00349 / 0.00232 | 0.0153 / 0.0111 |
| classified data seller tier 0/1 endpoint revenue busy | pooled | S | 6.06e-05 / 4.06e-05 | 0.000322 / 0.000231 |
| classified data seller tier 0/1 endpoint revenue busy | median | K10h | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue busy | median | N | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue busy | median | S | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | pooled | K10h | 0.00392 / 0.00184 | 0.0143 / 0.00829 |
| classified data seller tier 0/1 endpoint revenue median | pooled | N | 0.0039 / 0.00183 | 0.0158 / 0.00915 |
| classified data seller tier 0/1 endpoint revenue median | pooled | S | 7.31e-05 / 3.79e-05 | 0.000356 / 0.000206 |
| classified data seller tier 0/1 endpoint revenue median | median | K10h | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | median | N | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue median | median | S | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | K10h | 0.00425 / 0.00225 | 0.0155 / 0.00981 |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | N | 0.00424 / 0.00225 | 0.0173 / 0.0109 |
| classified data seller tier 0/1 endpoint revenue quiet | pooled | S | 7.98e-05 / 4.58e-05 | 0.000403 / 0.000254 |
| classified data seller tier 0/1 endpoint revenue quiet | median | K10h | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | median | N | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| classified data seller tier 0/1 endpoint revenue quiet | median | S | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | pooled | K10h | 0.00227 / 0.00221 | 0.0024 / 0.00234 |
| D94 | pooled | N | 0.00218 / 0.00211 | 0.00231 / 0.00224 |
| D94 | pooled | S | 3.52e-05 / 3.42e-05 | 3.76e-05 / 3.65e-05 |
| D94 | median | K10h | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | median | N | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| D94 | median | S | none(w 0) / none(w 0) | none(w 0) / none(w 0) |
| BlockRun(tier 1b) busy | pooled | K10h | 4.51e-05 / 4.35e-05 | 0.000235 / 0.000233 |
| BlockRun(tier 1b) busy | pooled | N | 4.31e-05 / 4.16e-05 | 0.000225 / 0.000223 |
| BlockRun(tier 1b) busy | pooled | S | 6.9e-07 / 6.65e-07 | 3.62e-06 / 3.59e-06 |
| BlockRun(tier 1b) median | pooled | K10h | 0.000113 / 0.000111 | 0.00043 / 0.000427 |
| BlockRun(tier 1b) median | pooled | N | 0.000108 / 0.000106 | 0.000411 / 0.000409 |
| BlockRun(tier 1b) median | pooled | S | 1.74e-06 / 1.71e-06 | 6.65e-06 / 6.62e-06 |
| BlockRun(tier 1b) quiet | pooled | K10h | 0.00466 / 0.00444 | 0.00975 / 0.00934 |
| BlockRun(tier 1b) quiet | pooled | N | 0.00451 / 0.00429 | 0.00982 / 0.00941 |
| BlockRun(tier 1b) quiet | pooled | S | 7.43e-05 / 7.07e-05 | 0.000176 / 0.000168 |

### 8b. w sensitivity (results seeing after added, for verdicts not used not): T01t pooled lower / upper, V 1 and 0.2

| window | V | mode | w 0 | w 0.0005 | w 0.00173 | w 0.005 |
|---|---|---|---|---|---|---|
| busy | 0.2 | N | 3.97% / 5.95% | 4.85% / 6.84% | 7.00% / 8.99% | 12.51% / 14.50% |
| busy | 0.2 | S | 3.94% / 5.90% | 43.80% / 45.76% | 84.75% / 86.71% | 99.61% / 101.57% |
| busy | 1 | N | 3.33% / 5.16% | 3.55% / 5.38% | 4.10% / 5.93% | 5.53% / 7.37% |
| busy | 1 | S | 3.41% / 5.23% | 13.44% / 15.26% | 33.89% / 35.72% | 67.67% / 69.50% |
| median | 0.2 | N | 5.17% / 7.70% | 5.80% / 8.34% | 7.34% / 9.88% | 11.32% / 13.86% |
| median | 0.2 | S | 4.87% / 7.31% | 34.87% / 37.31% | 74.24% / 76.68% | 98.23% / 100.67% |
| median | 1 | N | 4.36% / 6.70% | 4.54% / 6.88% | 4.99% / 7.33% | 6.17% / 8.51% |
| median | 1 | S | 4.38% / 6.70% | 12.17% / 14.49% | 28.73% / 31.05% | 59.11% / 61.43% |
| quiet | 0.2 | N | 5.09% / 7.36% | 5.68% / 7.96% | 7.12% / 9.40% | 10.86% / 13.14% |
| quiet | 0.2 | S | 4.80% / 6.98% | 33.02% / 35.20% | 71.70% / 73.89% | 97.50% / 99.69% |
| quiet | 1 | N | 4.27% / 6.35% | 4.44% / 6.52% | 4.85% / 6.93% | 5.95% / 8.03% |
| quiet | 1 | S | 4.30% / 6.35% | 11.33% / 13.39% | 26.51% / 28.56% | 55.41% / 57.47% |

## 9. verdict 2 (T01t pooled ≤ 10%, facilitator none, V 0.2 and 1, lower and upper)

| mode | case | V | busy | median | quiet | verdict |
|---|---|---|---|---|---|---|
| K10h | lower | 0.2 | 6.96% | 7.33% | 7.11% | holds |
| K10h | lower | 1 | 4.15% | 5.06% | 4.92% | holds |
| K10h | upper | 0.2 | 8.95% | 9.86% | 9.39% | holds |
| K10h | upper | 1 | 5.99% | 7.39% | 7.00% | holds |
| N | lower | 0.2 | 7.00% | 7.34% | 7.12% | holds |
| N | lower | 1 | 4.10% | 4.99% | 4.85% | holds |
| N | upper | 0.2 | 8.99% | 9.88% | 9.40% | holds |
| N | upper | 1 | 5.93% | 7.33% | 6.93% | holds |
| S | lower | 0.2 | 84.75% | 74.24% | 71.70% | does not hold not |
| S | lower | 1 | 33.89% | 28.73% | 26.51% | does not hold not |
| S | upper | 0.2 | 86.71% | 76.68% | 73.89% | does not hold not |
| S | upper | 1 | 35.72% | 31.05% | 28.56% | does not hold not |

## 10. p_max floor 1 gwei (D2): signature client preliminary

dispute open 1 KB 122,222 gas(L1 2,372,396,696 wei), decryption dispute 4 KB 186,500 gas(L1 26,662,241,764 wei), ETH 2401.44 USD. open purchase one preliminary: p_max 1 gwei 0.741447 USD(L2 0.741377, L1 0.000070), 0.0161 gwei 0.012006 USD. seller in totals p_max not entering so seller cost change 0.

| mode | D_open block | time |
|---|---|---|
| N | 2,250 | 1.25 |
| S | 137,970 | 76.65 |

per seller(V independent): preliminary/mean sales amount, preliminary capital cost revenue relative to share(r 10%), buyers concurrently lock reserve mean(USD):

| window | seller | R/n | preliminary / (R/n), 1 gwei | N share 1 gwei | S share 1 gwei | N share 0.0161 gwei | N concurrent preliminary 1 gwei | S concurrent preliminary 1 gwei | N seller retention L(optimum, lower) | S seller retention L |
|---|---|---|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 0.0380 | 19.5 | 0.03% | 1.71% | 0.00% | 70.56 | 4326.56 | 26.47 | 281.10 |
| busy | OneSource | 0.0043 | 172.6 | 0.25% | 15.10% | 0.00% | 13.23 | 811.21 | 5.45 | 10.85 |
| busy | CoinMarketCap | 0.0100 | 74.1 | 0.11% | 6.49% | 0.00% | 8.02 | 491.87 | 5.64 | 13.26 |
| busy | StableApify | 0.0155 | 47.8 | 0.07% | 4.18% | 0.00% | 0.35 | 21.76 | 1.01 | 1.54 |
| busy | Exa(0.001 or less) | 0.0010 | 741.4 | 1.06% | 64.88% | 0.02% | 0.43 | 26.50 | 0.20 | 0.24 |
| busy | CoinStats(0.01 or less) | 0.0015 | 505.5 | 0.72% | 44.23% | 0.01% | 0.08 | 5.07 | 0.20 | 0.21 |
| busy | BlockRun | 0.0109 | 68.0 | 0.10% | 5.95% | 0.00% | 17758.08 | 1088925.50 | 579.88 | 18965.27 |
| median | StableEnrich(Out candidates excluded) | 0.0363 | 20.4 | 0.03% | 1.79% | 0.00% | 57.44 | 3522.34 | 21.70 | 219.74 |
| median | OneSource | 0.0035 | 209.1 | 0.30% | 18.30% | 0.00% | 42.13 | 2583.26 | 6.20 | 20.37 |
| median | CoinMarketCap | 0.0100 | 74.1 | 0.11% | 6.49% | 0.00% | 0.30 | 18.38 | 0.51 | 1.29 |
| median | StableApify | 0.0116 | 64.1 | 0.09% | 5.61% | 0.00% | 0.10 | 6.09 | 0.50 | 0.61 |
| median | Exa(0.001 or less) | 0.0010 | 741.4 | 1.06% | 64.88% | 0.02% | 0.49 | 30.11 | 0.20 | 0.25 |
| median | CoinStats(0.01 or less) | 0.0010 | 741.4 | 1.06% | 64.88% | 0.02% | 0.05 | 3.16 | 0.20 | 0.21 |
| median | BlockRun | 0.0385 | 19.2 | 0.03% | 1.68% | 0.00% | 6103.83 | 374287.13 | 703.01 | 23026.41 |
| quiet | StableEnrich(Out candidates excluded) | 0.0261 | 28.4 | 0.04% | 2.49% | 0.00% | 71.74 | 4399.11 | 19.97 | 197.47 |
| quiet | OneSource | 0.0060 | 122.8 | 0.18% | 10.75% | 0.00% | 21.44 | 1314.87 | 6.04 | 18.32 |
| quiet | CoinMarketCap | 0.0100 | 74.1 | 0.11% | 6.49% | 0.00% | 0.24 | 15.00 | 0.51 | 0.74 |
| quiet | StableApify | 0.0092 | 80.3 | 0.11% | 7.03% | 0.00% | 0.07 | 4.10 | 0.20 | 0.26 |
| quiet | Exa(0.001 or less) | 0.0010 | 741.4 | 1.06% | 64.88% | 0.02% | 0.46 | 28.10 | 0.20 | 0.25 |
| quiet | CoinStats(0.01 or less) | 0.0010 | 741.4 | 1.06% | 64.88% | 0.02% | 0.03 | 1.74 | 0.20 | 0.20 |
| quiet | BlockRun | 0.0988 | 7.5 | 0.01% | 0.66% | 0.00% | 73.91 | 4532.35 | 63.45 | 756.59 |

## 11. component (σ 1, w 0.00173, facilitator none; pooled / median)

| set | V | case | mode | verify | anchor | sampvrf | release | l1 | detincl | failpath | frozen | deduct | capital | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | K10h | 0.0078 / 0.0067 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0033 / 0.0352 | 0.0002 / 0.0008 | - | - | 0.0274 / 0.0003 | 0.0025 / 0.0026 | 0.0001 / 0.0004 | 0.0696 / 0.2339 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | N | 0.0078 / 0.0067 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0033 / 0.0352 | 0.0002 / 0.0008 | - | - | 0.0287 / 0.0004 | 0.0017 / 0.0017 | 0.0001 / 0.0003 | 0.0700 / 0.2331 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | lower | S | 0.0066 / 0.0067 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0033 / 0.0352 | 0.0002 / 0.0008 | - | - | 0.8064 / 0.0219 | 0.0017 / 0.0017 | 0.0011 / 0.0013 | 0.8475 / 0.5804 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | K10h | 0.0081 / 0.0067 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0090 / 0.0600 | 0.0002 / 0.0008 | 0.0017 / 0.0017 | 0.0000 / 0.0005 | 0.0274 / 0.0003 | 0.0025 / 0.0026 | 0.0000 / 0.0003 | 0.0895 / 0.3660 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | N | 0.0081 / 0.0067 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0090 / 0.0600 | 0.0002 / 0.0008 | 0.0017 / 0.0017 | 0.0000 / 0.0005 | 0.0287 / 0.0004 | 0.0017 / 0.0018 | 0.0000 / 0.0002 | 0.0899 / 0.3652 |
| classified data seller tier 0/1 endpoint revenue busy | 0.2 | upper | S | 0.0066 / 0.0067 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0090 / 0.0600 | 0.0002 / 0.0008 | 0.0017 / 0.0017 | 0.0000 / 0.0005 | 0.8064 / 0.0219 | 0.0017 / 0.0018 | 0.0010 / 0.0012 | 0.8671 / 0.6821 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | K10h | 0.0016 / 0.0013 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0031 / 0.0350 | 0.0002 / 0.0008 | - | - | 0.0057 / 0.0001 | 0.0026 / 0.0026 | 0.0001 / 0.0016 | 0.0415 / 0.2037 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | N | 0.0016 / 0.0013 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0031 / 0.0350 | 0.0002 / 0.0008 | - | - | 0.0059 / 0.0001 | 0.0017 / 0.0017 | 0.0001 / 0.0011 | 0.0410 / 0.2028 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | lower | S | 0.0013 / 0.0013 | 0.0208 / 0.1212 | 0.0075 / 0.0626 | 0.0031 / 0.0350 | 0.0002 / 0.0008 | - | - | 0.3031 / 0.0044 | 0.0017 / 0.0017 | 0.0011 / 0.0021 | 0.3389 / 0.2887 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | K10h | 0.0016 / 0.0013 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0089 / 0.0598 | 0.0002 / 0.0008 | 0.0003 / 0.0003 | 0.0000 / 0.0005 | 0.0057 / 0.0001 | 0.0026 / 0.0026 | 0.0001 / 0.0016 | 0.0599 / 0.3322 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | N | 0.0016 / 0.0013 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0089 / 0.0598 | 0.0002 / 0.0008 | 0.0003 / 0.0003 | 0.0000 / 0.0005 | 0.0059 / 0.0001 | 0.0017 / 0.0017 | 0.0000 / 0.0011 | 0.0593 / 0.3309 |
| classified data seller tier 0/1 endpoint revenue busy | 1 | upper | S | 0.0013 / 0.0013 | 0.0208 / 0.1212 | 0.0198 / 0.1645 | 0.0089 / 0.0598 | 0.0002 / 0.0008 | 0.0003 / 0.0003 | 0.0000 / 0.0005 | 0.3031 / 0.0044 | 0.0017 / 0.0017 | 0.0011 / 0.0021 | 0.3572 / 0.3891 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | K10h | 0.0101 / 0.0067 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0042 / 0.1152 | 0.0002 / 0.0010 | - | - | 0.0192 / 0.0000 | 0.0023 / 0.0026 | 0.0001 / 0.0019 | 0.0733 / 0.4285 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | N | 0.0101 / 0.0067 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0042 / 0.1152 | 0.0002 / 0.0010 | - | - | 0.0201 / 0.0000 | 0.0016 / 0.0017 | 0.0001 / 0.0013 | 0.0734 / 0.4271 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | lower | S | 0.0060 / 0.0067 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0042 / 0.1152 | 0.0002 / 0.0010 | - | - | 0.6922 / 0.0015 | 0.0016 / 0.0017 | 0.0011 / 0.0023 | 0.7424 / 0.6166 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | K10h | 0.0110 / 0.0067 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0116 / 0.1152 | 0.0002 / 0.0010 | 0.0015 / 0.0017 | 0.0000 / 0.0028 | 0.0192 / 0.0000 | 0.0023 / 0.0026 | 0.0000 / 0.0019 | 0.0986 / 0.6376 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | N | 0.0110 / 0.0067 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0116 / 0.1152 | 0.0002 / 0.0010 | 0.0015 / 0.0017 | 0.0000 / 0.0028 | 0.0201 / 0.0000 | 0.0016 / 0.0018 | 0.0000 / 0.0013 | 0.0988 / 0.6361 |
| classified data seller tier 0/1 endpoint revenue median | 0.2 | upper | S | 0.0060 / 0.0067 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0116 / 0.1152 | 0.0002 / 0.0010 | 0.0015 / 0.0017 | 0.0000 / 0.0028 | 0.6922 / 0.0015 | 0.0016 / 0.0018 | 0.0010 / 0.0023 | 0.7668 / 0.7398 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | K10h | 0.0021 / 0.0013 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0041 / 0.1150 | 0.0002 / 0.0010 | - | - | 0.0043 / 0.0000 | 0.0026 / 0.0026 | 0.0001 / 0.0095 | 0.0506 / 0.4305 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | N | 0.0021 / 0.0013 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0041 / 0.1150 | 0.0002 / 0.0010 | - | - | 0.0045 / 0.0000 | 0.0017 / 0.0017 | 0.0001 / 0.0064 | 0.0499 / 0.4266 |
| classified data seller tier 0/1 endpoint revenue median | 1 | lower | S | 0.0013 / 0.0013 | 0.0276 / 0.1758 | 0.0095 / 0.1256 | 0.0041 / 0.1150 | 0.0002 / 0.0010 | - | - | 0.2418 / 0.0003 | 0.0017 / 0.0017 | 0.0011 / 0.0074 | 0.2873 / 0.4279 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | K10h | 0.0023 / 0.0013 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0114 / 0.1150 | 0.0002 / 0.0010 | 0.0003 / 0.0003 | 0.0000 / 0.0028 | 0.0043 / 0.0000 | 0.0026 / 0.0026 | 0.0001 / 0.0095 | 0.0739 / 0.6382 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | N | 0.0023 / 0.0013 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0114 / 0.1150 | 0.0002 / 0.0010 | 0.0003 / 0.0003 | 0.0000 / 0.0028 | 0.0045 / 0.0000 | 0.0017 / 0.0017 | 0.0001 / 0.0064 | 0.0733 / 0.6343 |
| classified data seller tier 0/1 endpoint revenue median | 1 | upper | S | 0.0013 / 0.0013 | 0.0276 / 0.1758 | 0.0251 / 0.3301 | 0.0114 / 0.1150 | 0.0002 / 0.0010 | 0.0003 / 0.0003 | 0.0000 / 0.0028 | 0.2418 / 0.0003 | 0.0017 / 0.0017 | 0.0011 / 0.0074 | 0.3105 / 0.6356 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | K10h | 0.0101 / 0.0067 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0046 / 0.1820 | 0.0002 / 0.0009 | - | - | 0.0179 / 0.0000 | 0.0024 / 0.0026 | 0.0001 / 0.0032 | 0.0711 / 0.6630 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | N | 0.0101 / 0.0067 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0046 / 0.1820 | 0.0002 / 0.0009 | - | - | 0.0187 / 0.0000 | 0.0016 / 0.0017 | 0.0001 / 0.0022 | 0.0712 / 0.6611 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | lower | S | 0.0062 / 0.0067 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0046 / 0.1820 | 0.0002 / 0.0009 | - | - | 0.6674 / 0.0011 | 0.0016 / 0.0017 | 0.0011 / 0.0032 | 0.7170 / 0.7082 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | K10h | 0.0111 / 0.0067 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0109 / 0.1820 | 0.0002 / 0.0009 | 0.0016 / 0.0017 | 0.0000 / 0.0065 | 0.0179 / 0.0000 | 0.0024 / 0.0026 | 0.0000 / 0.0032 | 0.0939 / 1.0002 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | N | 0.0111 / 0.0067 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0109 / 0.1820 | 0.0002 / 0.0009 | 0.0016 / 0.0017 | 0.0000 / 0.0065 | 0.0187 / 0.0000 | 0.0016 / 0.0018 | 0.0000 / 0.0022 | 0.0940 / 0.9983 |
| classified data seller tier 0/1 endpoint revenue quiet | 0.2 | upper | S | 0.0062 / 0.0067 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0109 / 0.1820 | 0.0002 / 0.0009 | 0.0016 / 0.0017 | 0.0000 / 0.0065 | 0.6674 / 0.0011 | 0.0016 / 0.0018 | 0.0010 / 0.0032 | 0.7389 / 1.0004 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | K10h | 0.0021 / 0.0013 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0044 / 0.1818 | 0.0002 / 0.0009 | - | - | 0.0039 / 0.0000 | 0.0026 / 0.0026 | 0.0001 / 0.0159 | 0.0492 / 0.6701 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | N | 0.0021 / 0.0013 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0044 / 0.1818 | 0.0002 / 0.0009 | - | - | 0.0041 / 0.0000 | 0.0017 / 0.0017 | 0.0001 / 0.0108 | 0.0485 / 0.6641 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | lower | S | 0.0013 / 0.0013 | 0.0274 / 0.2656 | 0.0085 / 0.2020 | 0.0044 / 0.1818 | 0.0002 / 0.0009 | - | - | 0.2204 / 0.0002 | 0.0017 / 0.0017 | 0.0011 / 0.0118 | 0.2651 / 0.6653 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | K10h | 0.0023 / 0.0013 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0107 / 0.1818 | 0.0002 / 0.0009 | 0.0003 / 0.0003 | 0.0000 / 0.0065 | 0.0039 / 0.0000 | 0.0026 / 0.0026 | 0.0001 / 0.0159 | 0.0700 / 1.0059 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | N | 0.0023 / 0.0013 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0107 / 0.1818 | 0.0002 / 0.0009 | 0.0003 / 0.0003 | 0.0000 / 0.0065 | 0.0041 / 0.0000 | 0.0017 / 0.0017 | 0.0001 / 0.0108 | 0.0693 / 0.9999 |
| classified data seller tier 0/1 endpoint revenue quiet | 1 | upper | S | 0.0013 / 0.0013 | 0.0274 / 0.2656 | 0.0225 / 0.5310 | 0.0107 / 0.1818 | 0.0002 / 0.0009 | 0.0003 / 0.0003 | 0.0000 / 0.0065 | 0.2204 / 0.0002 | 0.0017 / 0.0017 | 0.0011 / 0.0118 | 0.2856 / 1.0012 |
| D94 | 0.2 | lower | K10h | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0400 | 0.0000 / 0.0006 | - | - | 0.0713 / 0.0001 | 0.0003 / 0.0026 | 0.0000 / 0.0005 | 0.0787 / 0.3110 |
| D94 | 0.2 | lower | N | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0400 | 0.0000 / 0.0006 | - | - | 0.0745 / 0.0001 | 0.0002 / 0.0017 | 0.0000 / 0.0004 | 0.0818 / 0.3101 |
| D94 | 0.2 | lower | S | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0400 | 0.0000 / 0.0006 | - | - | 0.9397 / 0.0039 | 0.0002 / 0.0017 | 0.0011 / 0.0014 | 0.9480 / 0.4242 |
| D94 | 0.2 | upper | K10h | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0970 | 0.0000 / 0.0007 | 0.0002 / 0.0017 | 0.0000 / 0.0007 | 0.0713 / 0.0001 | 0.0003 / 0.0026 | 0.0000 / 0.0005 | 0.0812 / 0.5364 |
| D94 | 0.2 | upper | N | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0970 | 0.0000 / 0.0007 | 0.0002 / 0.0017 | 0.0000 / 0.0007 | 0.0745 / 0.0001 | 0.0002 / 0.0018 | 0.0000 / 0.0003 | 0.0843 / 0.5351 |
| D94 | 0.2 | upper | S | 0.0007 / 0.0067 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0970 | 0.0000 / 0.0007 | 0.0002 / 0.0017 | 0.0000 / 0.0007 | 0.9397 / 0.0039 | 0.0002 / 0.0018 | 0.0010 / 0.0013 | 0.9505 / 0.7207 |
| D94 | 1 | lower | K10h | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0398 | 0.0000 / 0.0006 | - | - | 0.0672 / 0.0000 | 0.0009 / 0.0026 | 0.0001 / 0.0023 | 0.0750 / 0.3064 |
| D94 | 1 | lower | N | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0398 | 0.0000 / 0.0006 | - | - | 0.0702 / 0.0000 | 0.0006 / 0.0017 | 0.0001 / 0.0016 | 0.0777 / 0.3051 |
| D94 | 1 | lower | S | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0010 / 0.1072 | 0.0008 / 0.0398 | 0.0000 / 0.0006 | - | - | 0.9144 / 0.0010 | 0.0006 / 0.0017 | 0.0011 / 0.0026 | 0.9229 / 0.3856 |
| D94 | 1 | upper | K10h | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0968 | 0.0000 / 0.0007 | 0.0001 / 0.0003 | 0.0000 / 0.0007 | 0.0672 / 0.0000 | 0.0009 / 0.0026 | 0.0000 / 0.0023 | 0.0774 / 0.5368 |
| D94 | 1 | upper | N | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0968 | 0.0000 / 0.0007 | 0.0001 / 0.0003 | 0.0000 / 0.0007 | 0.0702 / 0.0000 | 0.0006 / 0.0017 | 0.0000 / 0.0016 | 0.0801 / 0.5333 |
| D94 | 1 | upper | S | 0.0005 / 0.0013 | 0.0045 / 0.1719 | 0.0026 / 0.2817 | 0.0015 / 0.0968 | 0.0000 / 0.0007 | 0.0001 / 0.0003 | 0.0000 / 0.0007 | 0.9144 / 0.0010 | 0.0006 / 0.0017 | 0.0010 / 0.0026 | 0.9253 / 0.6277 |
| BlockRun(tier 1b) busy | 0.2 | lower | K10h | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | - | - | 0.8786 / 0.8786 | 0.0025 / 0.0025 | 0.0000 / 0.0000 | 0.9275 / 0.9275 |
| BlockRun(tier 1b) busy | 0.2 | lower | N | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | - | - | 0.8899 / 0.8899 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.9381 / 0.9381 |
| BlockRun(tier 1b) busy | 0.2 | lower | S | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | - | - | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0492 / 1.0492 |
| BlockRun(tier 1b) busy | 0.2 | upper | K10h | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.8786 / 0.8786 | 0.0025 / 0.0025 | 0.0000 / 0.0000 | 0.9294 / 0.9294 |
| BlockRun(tier 1b) busy | 0.2 | upper | N | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.8899 / 0.8899 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.9399 / 0.9399 |
| BlockRun(tier 1b) busy | 0.2 | upper | S | 0.0043 / 0.0043 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0068 / 0.0068 | 0.0004 / 0.0004 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0510 / 1.0510 |
| BlockRun(tier 1b) busy | 1 | lower | K10h | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | - | - | 0.3497 / 0.3497 | 0.0026 / 0.0026 | 0.0000 / 0.0000 | 0.3951 / 0.3951 |
| BlockRun(tier 1b) busy | 1 | lower | N | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | - | - | 0.3626 / 0.3626 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.4072 / 0.4072 |
| BlockRun(tier 1b) busy | 1 | lower | S | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0001 / 0.0001 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | - | - | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0456 / 1.0456 |
| BlockRun(tier 1b) busy | 1 | upper | K10h | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.3497 / 0.3497 | 0.0026 / 0.0026 | 0.0000 / 0.0000 | 0.3957 / 0.3957 |
| BlockRun(tier 1b) busy | 1 | upper | N | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.3626 / 0.3626 | 0.0017 / 0.0017 | 0.0000 / 0.0000 | 0.4077 / 0.4077 |
| BlockRun(tier 1b) busy | 1 | upper | S | 0.0009 / 0.0009 | 0.0349 / 0.0349 | 0.0002 / 0.0002 | 0.0066 / 0.0066 | 0.0004 / 0.0004 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0017 / 0.0017 | 0.0010 / 0.0010 | 1.0461 / 1.0461 |
| BlockRun(tier 1b) median | 0.2 | lower | K10h | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | - | - | 0.7464 / 0.7464 | 0.0013 / 0.0013 | 0.0000 / 0.0000 | 0.7621 / 0.7621 |
| BlockRun(tier 1b) median | 0.2 | lower | N | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | - | - | 0.7620 / 0.7620 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7774 / 0.7774 |
| BlockRun(tier 1b) median | 0.2 | lower | S | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | - | - | 1.0000 / 1.0000 | 0.0009 / 0.0009 | 0.0010 / 0.0010 | 1.0163 / 1.0163 |
| BlockRun(tier 1b) median | 0.2 | upper | K10h | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7464 / 0.7464 | 0.0014 / 0.0014 | 0.0000 / 0.0000 | 0.7632 / 0.7632 |
| BlockRun(tier 1b) median | 0.2 | upper | N | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7620 / 0.7620 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 0.7784 / 0.7784 |
| BlockRun(tier 1b) median | 0.2 | upper | S | 0.0023 / 0.0023 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0020 / 0.0020 | 0.0001 / 0.0001 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0009 / 0.0009 | 0.0010 / 0.0010 | 1.0174 / 1.0174 |
| BlockRun(tier 1b) median | 1 | lower | K10h | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | - | - | 0.3067 / 0.3067 | 0.0018 / 0.0018 | 0.0000 / 0.0000 | 0.3211 / 0.3211 |
| BlockRun(tier 1b) median | 1 | lower | N | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | - | - | 0.3184 / 0.3184 | 0.0012 / 0.0012 | 0.0000 / 0.0000 | 0.3322 / 0.3322 |
| BlockRun(tier 1b) median | 1 | lower | S | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0001 / 0.0001 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | - | - | 1.0000 / 1.0000 | 0.0012 / 0.0012 | 0.0010 / 0.0010 | 1.0148 / 1.0148 |
| BlockRun(tier 1b) median | 1 | upper | K10h | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.3067 / 0.3067 | 0.0018 / 0.0018 | 0.0000 / 0.0000 | 0.3215 / 0.3215 |
| BlockRun(tier 1b) median | 1 | upper | N | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 0.3184 / 0.3184 | 0.0012 / 0.0012 | 0.0000 / 0.0000 | 0.3326 / 0.3326 |
| BlockRun(tier 1b) median | 1 | upper | S | 0.0006 / 0.0006 | 0.0099 / 0.0099 | 0.0002 / 0.0002 | 0.0019 / 0.0019 | 0.0001 / 0.0001 | 0.0002 / 0.0002 | 0.0000 / 0.0000 | 1.0000 / 1.0000 | 0.0012 / 0.0012 | 0.0010 / 0.0010 | 1.0152 / 1.0152 |
| BlockRun(tier 1b) quiet | 0.2 | lower | K10h | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | - | - | 0.0334 / 0.0334 | 0.0011 / 0.0011 | 0.0001 / 0.0001 | 0.0441 / 0.0441 |
| BlockRun(tier 1b) quiet | 0.2 | lower | N | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | - | - | 0.0349 / 0.0349 | 0.0007 / 0.0007 | 0.0001 / 0.0001 | 0.0453 / 0.0453 |
| BlockRun(tier 1b) quiet | 0.2 | lower | S | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0009 / 0.0009 | 0.0000 / 0.0000 | - | - | 0.8868 / 0.8868 | 0.0007 / 0.0007 | 0.0011 / 0.0011 | 0.8982 / 0.8982 |
| BlockRun(tier 1b) quiet | 0.2 | upper | K10h | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.0334 / 0.0334 | 0.0011 / 0.0011 | 0.0000 / 0.0000 | 0.0482 / 0.0482 |
| BlockRun(tier 1b) quiet | 0.2 | upper | N | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.0349 / 0.0349 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.0494 / 0.0494 |
| BlockRun(tier 1b) quiet | 0.2 | upper | S | 0.0018 / 0.0018 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0007 / 0.0007 | 0.0000 / 0.0000 | 0.8868 / 0.8868 | 0.0007 / 0.0007 | 0.0010 / 0.0010 | 0.9022 / 0.9022 |
| BlockRun(tier 1b) quiet | 1 | lower | K10h | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.0144 / 0.0144 | 0.0023 / 0.0023 | 0.0001 / 0.0001 | 0.0252 / 0.0252 |
| BlockRun(tier 1b) quiet | 1 | lower | N | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.0151 / 0.0151 | 0.0015 / 0.0015 | 0.0001 / 0.0001 | 0.0252 / 0.0252 |
| BlockRun(tier 1b) quiet | 1 | lower | S | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0014 / 0.0014 | 0.0008 / 0.0008 | 0.0000 / 0.0000 | - | - | 0.6062 / 0.6062 | 0.0015 / 0.0015 | 0.0011 / 0.0011 | 0.6173 / 0.6173 |
| BlockRun(tier 1b) quiet | 1 | upper | K10h | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0144 / 0.0144 | 0.0023 / 0.0023 | 0.0000 / 0.0000 | 0.0289 / 0.0289 |
| BlockRun(tier 1b) quiet | 1 | upper | N | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.0151 / 0.0151 | 0.0015 / 0.0015 | 0.0000 / 0.0000 | 0.0289 / 0.0289 |
| BlockRun(tier 1b) quiet | 1 | upper | S | 0.0008 / 0.0008 | 0.0054 / 0.0054 | 0.0037 / 0.0037 | 0.0020 / 0.0020 | 0.0000 / 0.0000 | 0.0003 / 0.0003 | 0.0000 / 0.0000 | 0.6062 / 0.6062 | 0.0015 / 0.0015 | 0.0010 / 0.0010 | 0.6210 / 0.6210 |

## 12. independent for checking three cells input

constant: 1 gas = gp × 1e-9 × ETH USD, gp = 0.005 + (2.0 − 1) × 0.005 = 0.010 gwei, ETH 2401.44. 1 wei(L1) = 1e-18 × ETH USD. anchor(σ 1) run gas = 148,812 + 15,668 x, EIP-7623 lower gas = 28120.0000 + 13562.5000 x, two among large value(x = n / A_p). anchor L1 wei = A_p × 1870582712.0000 + n × 1566632536.1250. release gas = Ru × 114,624 + 2,930 n + 2,083 n_s (ledger), release L1 wei = Ru × 945606403.8667 + n × 245940057.8917. sample request and ECVRF = (51,550 + 80,900) gas + (734,567,965 + 2,593,604,493) wei. Chainlink(upper) = gusd(96,000) + wusd(734,567,965) + 1.60 × (gusd(157,644) + wusd(4,321,371,668)). determinism and included(upper) = (5,200 n_s + depth × 900 × n_s) gas, failure path 104,276 gas(per period one time and expected per failure). W_b = days × 43,200.

proof price: RS3 = gusd(55,556) + wusd(2,132,754,915) = 0.00133927 USD. SP0(lower) = gusd(552,125) + wusd(28,173,828,378) + gusd(5,000) = 0.01344668 USD, SP0(upper) = gusd(672,029) + wusd(28,173,828,378) + gusd(5,000) = 0.01632610 USD. upper Merkle depth(σ 1) = 10.

### median, CoinMarketCap, V 1, lower, mode N

- input: R = 1.630000 USDC, n = 163, n_s = 1.630000, days 21, E_p(activity profile epoch) = 58, A_p = 58, chosen k = 1, E(k) = 58, Ru(release count) = 58, proof RS3 c_P = 0.00133927 USD, b = 1.000000, H(k) = 4,051, Δ_f = 2,251, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.001339, anchor 0.164786, sampvrf 0.113463, release 0.105032, l1 0.000676, frozen 0.000007, deduct 0.001730, capital 0.003555, total 0.390589 (= 39.06%)
- other k total: k 1 0.390589, k 2 0.390591, k 4 0.390594, k 8 0.390602, k 16 0.390617, k 32 0.390648

### busy, StableEnrich(Out candidates excluded), V 1, lower, mode S

- input: R = 1458.904400 USDC, n = 38369, n_s = 1458.904400, days 21, E_p(activity profile epoch) = 2046, A_p = 2046, chosen k = 32, E(k) = 95, Ru(release count) = 95, proof RS3 c_P = 0.00133927 USD, b = 1.000000, H(k) = 171,691, Δ_f = 137,971, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.001339, anchor 0.014907, sampvrf 0.004472, release 0.002080, l1 0.000121, frozen 0.318764, deduct 0.001730, capital 0.001093, total 0.344506 (= 34.45%)
- other k total: k 1 0.348131, k 2 0.347125, k 4 0.345701, k 8 0.344995, k 16 0.344653, k 32 0.344506

### quiet, OneSource, V 0.2, upper, mode N

- input: R = 50.279000 USDC, n = 8329, n_s = 251.395000, days 15, E_p(activity profile epoch) = 543, A_p = 543, chosen k = 1, E(k) = 543, Ru(release count) = 543, proof SP0 c_P = 0.01632610 USD, b = 0.200000, H(k) = 4,051, Δ_f = 2,251, w = 0.00173, r 0.10, a 0.
- component(revenue relative to): verify 0.081631, anchor 0.100923, sampvrf 0.090512, release 0.041634, l1 0.000794, detincl 0.001705, failpath 0.000050, frozen 0.001510, deduct 0.001752, capital 0.000042, total 0.320552 (= 32.06%)
- other k total: k 1 0.320552, k 2 0.320553, k 4 0.320557, k 8 0.320565, k 16 0.320580, k 32 0.320611

