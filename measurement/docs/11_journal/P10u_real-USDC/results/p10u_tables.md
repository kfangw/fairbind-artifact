**all values post hoc calculations registered verdict none.** `p10.py` output. P11 V1u(measured VRF, real USDC release and anchor), mode N, σ 1, r 10%, a 0, w 0.00173, V 1, per seller optimal k. costs revenue relative to %, R_e active profile per epoch revenue(USDC).

reproduction(`--check`): observed seller closed form vs p11.json V1u p9cells max difference FairBind 2.2e-14%p, FI 0.0e+00%p, k mismatch 0; stylised seller vs P9 Env max difference 0.0e+00%p, k mismatch 0. admission 0.05%p.

## 1. threshold (stylised seller, 21 days window, tier 1a proof)

R_e USDC, in parentheses sales count m and then k. "below" cost share threshold below entering R_e, "upper" freeze term because again over R_e. FI crossing two design cost share equalizing R_e(→ after its above more cheaper side).

| case | d | v̄ | 10% below | 10% upper | 5% below | 5% upper | min cost share | FI crossing |
|---|---|---|---|---|---|---|---|---|
| lower | 1 | 0.001 | none | none | none | none | 129.06 | 0.01325 → FB |
| lower | 0.1 | 0.001 | none | none | none | none | 128.53 | 0.01326 → FB |
| lower | 1 | 0.002 | none | none | none | none | 65.31 | 0.02655 → FB; 87.81 → FI |
| lower | 0.1 | 0.002 | none | none | none | none | 64.74 | 0.02656 → FB; 880.4 → FI |
| lower | 1 | 0.005 | none | none | none | none | 27.69 | 0.0669 → FB; 24.16 → FI |
| lower | 0.1 | 0.005 | none | none | none | none | 26.25 | 0.06676 → FB; 243.6 → FI |
| lower | 1 | 0.01 | none | none | none | none | 15.51 | 0.1364 → FB; 10.74 → FI |
| lower | 0.1 | 0.01 | none | none | none | none | 13.55 | 0.1348 → FB; 111 → FI |
| lower | 1 | 0.02 | 0.6127 (m 30.64, k 8) | 2.138 (m 106.9, k 2) | none | none | 9.41 | 0.2914 → FB; 4.569 → FI |
| lower | 0.1 | 0.02 | 0.5394 (m 26.97, k 1) | 24.26 (m 1213, k 16) | none | none | 7.42 | 0.2754 → FB; 52.08 → FI |
| lower | 1 | 0.05 | 0.2446 (m 4.891, k 32) | 5.486 (m 109.7, k 2) | none | none | 5.76 | none(increase FI) |
| lower | 0.1 | 0.05 | 0.2434 (m 4.868, k 32) | 55.96 (m 1119, k 2) | 0.9073 (m 18.15, k 1) | 13.32 (m 266.5, k 32) | 3.79 | 0.7527 → FB; 17.65 → FI |
| lower | 1 | 0.1 | 0.2067 (m 2.067, k 32) | 6.537 (m 65.37, k 2) | 0.6595 (m 6.595, k 32) | 1.992 (m 19.92, k 8) | 4.54 | none(increase FI) |
| lower | 0.1 | 0.1 | 0.2081 (m 2.081, k 32) | 66.67 (m 666.7, k 4) | 0.5228 (m 5.228, k 32) | 25.6 (m 256, k 1) | 2.58 | 2.149 → FB; 6.051 → FI |
| lower | 1 | 0.2 | from the start below | 7.069 (m 35.35, k 4) | 0.5006 (m 2.503, k 32) | 2.642 (m 13.21, k 16) | 3.94 | none(increase FI) |
| lower | 0.1 | 0.2 | from the start below | 72.05 (m 360.3, k 2) | 0.4414 (m 2.207, k 32) | 31.1 (m 155.5, k 1) | 1.97 | none(increase FI) |
| lower | 1 | 0.5 | from the start below | 7.388 (m 14.78, k 16) | from the start below | 2.991 (m 5.982, k 16) | 3.57 | none(increase FI) |
| lower | 0.1 | 0.5 | from the start below | 75.73 (m 151.5, k 1) | from the start below | 34.07 (m 68.13, k 1) | 1.58 | none(increase FI) |
| lower | 1 | 1 | from the start below | 7.493 (m 7.493, k 16) | from the start below | 3.105 (m 3.105, k 16) | 3.45 | none(increase FI) |
| lower | 0.1 | 1 | from the start below | 76.76 (m 76.76, k 1) | from the start below | 35.06 (m 35.06, k 1) | 1.46 | none(increase FI) |
| upper | 1 | 0.001 | none | none | none | none | 129.09 | 0.01202 → FB |
| upper | 0.1 | 0.001 | none | none | none | none | 128.57 | 0.01204 → FB |
| upper | 1 | 0.002 | none | none | none | none | 65.34 | 0.02409 → FB; 105.1 → FI |
| upper | 0.1 | 0.002 | none | none | none | none | 64.77 | 0.02412 → FB; 1054 → FI |
| upper | 1 | 0.005 | none | none | none | none | 27.72 | 0.06069 → FB; 26.9 → FI |
| upper | 0.1 | 0.005 | none | none | none | none | 26.28 | 0.06063 → FB; 271.2 → FI |
| upper | 1 | 0.01 | none | none | none | none | 15.62 | 0.1235 → FB; 11.92 → FI |
| upper | 0.1 | 0.01 | none | none | none | none | 13.58 | 0.1224 → FB; 122.4 → FI |
| upper | 1 | 0.02 | 0.7245 (m 36.22, k 1) | 2.042 (m 102.1, k 1) | none | none | 9.58 | 0.2617 → FB; 5.106 → FI |
| upper | 0.1 | 0.02 | 0.5445 (m 27.22, k 1) | 23.97 (m 1198, k 1) | none | none | 7.45 | 0.2501 → FB; 57.25 → FI |
| upper | 1 | 0.05 | 0.2771 (m 5.541, k 1) | 5.443 (m 108.9, k 1) | none | none | 5.95 | none(increase FI) |
| upper | 0.1 | 0.05 | 0.2648 (m 5.296, k 1) | 55.68 (m 1114, k 1) | 0.9219 (m 18.44, k 1) | 12.8 (m 256, k 1) | 3.82 | 0.6805 → FB; 19.71 → FI |
| upper | 1 | 0.1 | 0.2336 (m 2.336, k 1) | 6.497 (m 64.97, k 1) | 0.8082 (m 8.082, k 1) | 1.829 (m 18.29, k 1) | 4.74 | none(increase FI) |
| upper | 0.1 | 0.1 | 0.2263 (m 2.263, k 1) | 66.41 (m 664.1, k 1) | 0.5718 (m 5.718, k 1) | 25.6 (m 256, k 1) | 2.61 | 1.82 → FB; 7.152 → FI |
| upper | 1 | 0.2 | 0.2168 (m 1.084, k 1) | 7.024 (m 35.12, k 1) | 0.5847 (m 2.924, k 1) | 2.536 (m 12.68, k 1) | 4.13 | none(increase FI) |
| upper | 0.1 | 0.2 | 0.2109 (m 1.055, k 1) | 71.78 (m 358.9, k 1) | 0.4819 (m 2.409, k 1) | 30.86 (m 154.3, k 1) | 2.01 | none(increase FI) |
| upper | 1 | 0.5 | from the start below | 7.34 (m 14.68, k 1) | 0.5123 (m 1.025, k 1) | 2.9 (m 5.801, k 1) | 3.77 | none(increase FI) |
| upper | 0.1 | 0.5 | from the start below | 75.47 (m 150.9, k 1) | from the start below | 33.82 (m 67.64, k 1) | 1.64 | none(increase FI) |
| upper | 1 | 1 | from the start below | 7.446 (m 7.446, k 1) | from the start below | 3.017 (m 3.017, k 1) | 3.65 | none(increase FI) |
| upper | 0.1 | 1 | from the start below | 76.5 (m 76.5, k 1) | from the start below | 34.81 (m 34.81, k 1) | 1.52 | none(increase FI) |
| facilitator | 1 | 0.001 | none | none | none | none | 277.02 | 0.01325 → FB |
| facilitator | 0.1 | 0.001 | none | none | none | none | 276.33 | 0.01326 → FB |
| facilitator | 1 | 0.002 | none | none | none | none | 139.29 | 0.02655 → FB; 87.81 → FI |
| facilitator | 0.1 | 0.002 | none | none | none | none | 138.72 | 0.02656 → FB; 880.4 → FI |
| facilitator | 1 | 0.005 | none | none | none | none | 57.28 | 0.0669 → FB; 24.16 → FI |
| facilitator | 0.1 | 0.005 | none | none | none | none | 55.84 | 0.06676 → FB; 243.6 → FI |
| facilitator | 1 | 0.01 | none | none | none | none | 30.32 | 0.1364 → FB; 10.74 → FI |
| facilitator | 0.1 | 0.01 | none | none | none | none | 28.35 | 0.1348 → FB; 111 → FI |
| facilitator | 1 | 0.02 | none | none | none | none | 16.84 | 0.2914 → FB; 4.569 → FI |
| facilitator | 0.1 | 0.02 | none | none | none | none | 14.82 | 0.2754 → FB; 52.08 → FI |
| facilitator | 1 | 0.05 | 0.4774 (m 9.548, k 16) | 2.84 (m 56.8, k 4) | none | none | 8.76 | none(increase FI) |
| facilitator | 0.1 | 0.05 | 0.4423 (m 8.846, k 16) | 31.29 (m 625.8, k 2) | none | none | 6.76 | 0.7527 → FB; 17.65 → FI |
| facilitator | 1 | 0.1 | 0.2616 (m 2.616, k 32) | 5.254 (m 52.54, k 4) | none | none | 6.06 | none(increase FI) |
| facilitator | 0.1 | 0.1 | 0.2589 (m 2.589, k 32) | 54.15 (m 541.5, k 4) | 1.031 (m 10.31, k 16) | 13.95 (m 139.5, k 1) | 4.07 | 2.149 → FB; 6.051 → FI |
| facilitator | 1 | 0.2 | 0.2156 (m 1.078, k 32) | 6.422 (m 32.11, k 4) | 0.7487 (m 3.744, k 32) | 1.801 (m 9.006, k 16) | 4.71 | none(increase FI) |
| facilitator | 0.1 | 0.2 | 0.2165 (m 1.083, k 32) | 65.74 (m 328.7, k 2) | 0.5583 (m 2.792, k 32) | 25.06 (m 125.3, k 1) | 2.72 | none(increase FI) |
| facilitator | 1 | 0.5 | from the start below | 7.125 (m 14.25, k 16) | 0.5032 (m 1.006, k 32) | 2.693 (m 5.386, k 16) | 3.91 | none(increase FI) |
| facilitator | 0.1 | 0.5 | from the start below | 73.21 (m 146.4, k 1) | from the start below | 31.64 (m 63.29, k 1) | 1.89 | none(increase FI) |
| facilitator | 1 | 1 | from the start below | 7.359 (m 7.359, k 16) | from the start below | 2.953 (m 2.953, k 16) | 3.64 | none(increase FI) |
| facilitator | 0.1 | 1 | from the start below | 75.5 (m 75.5, k 1) | from the start below | 33.84 (m 33.84, k 1) | 1.62 | none(increase FI) |

### closed form, lower (freeze and capital without R_e* = c / (θ − a − b / v̄), d 1, m k ≤ 256, v̄ ≤ V; - θ ≤ a + b / v̄d threshold none)

| case | v̄ | k | θ | a | b (USDC/sales) | c (USDC/epoch) | R_e* |
|---|---|---|---|---|---|---|---|
| lower | 0.02 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01886 | 0.528 |
| lower | 0.02 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01886 | - |
| lower | 0.02 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01701 | 0.4761 |
| lower | 0.02 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01701 | - |
| lower | 0.02 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01681 | 0.4706 |
| lower | 0.02 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01681 | - |
| lower | 0.05 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01886 | 0.2619 |
| lower | 0.05 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01886 | 0.8569 |
| lower | 0.05 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01701 | 0.2362 |
| lower | 0.05 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01701 | 0.7729 |
| lower | 0.05 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01681 | 0.2335 |
| lower | 0.05 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01681 | 0.7638 |
| lower | 0.1 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01886 | 0.2243 |
| lower | 0.1 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01886 | 0.5531 |
| lower | 0.1 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01701 | 0.2023 |
| lower | 0.1 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01701 | 0.4988 |
| lower | 0.1 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01681 | 0.1999 |
| lower | 0.1 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01681 | 0.493 |
| lower | 0.2 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01886 | 0.2092 |
| lower | 0.2 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01886 | 0.4698 |
| lower | 0.2 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01701 | 0.1887 |
| lower | 0.2 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01701 | 0.4237 |
| lower | 0.2 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01681 | 0.1865 |
| lower | 0.2 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01681 | 0.4187 |

## 2. observed seller (V1u, V 1)

| window | seller | case | R_e | m | v̄ | k* | R / E_k* | FairBind | FI | more cheaper side | stylised curve FairBind | stylised curve FI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | 0.7131 | 18.75 | 0.03802 | 4 | 1.93 | 6.76 | 6.91 | FairBind | 6.59 | 6.74 |
| busy | StableEnrich(Out candidates excluded) | upper | 0.7131 | 18.75 | 0.03802 | 1 | 0.7131 | 6.90 | 7.36 | FairBind | 6.86 | 7.32 |
| busy | StableEnrich(Out candidates excluded) | facilitator | 0.7131 | 18.75 | 0.03802 | 4 | 1.93 | 10.70 | 10.85 | FairBind | 10.54 | 10.69 |
| busy | OneSource | lower | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 45.71 | 353.49 | FairBind | 44.13 | 59.55 |
| busy | OneSource | upper | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 46.04 | 423.52 | FairBind | 44.17 | 62.56 |
| busy | OneSource | facilitator | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 80.45 | 388.23 | FairBind | 78.87 | 94.29 |
| busy | CoinMarketCap | lower | 0.04073 | 4.073 | 0.01 | 32 | 0.4592 | 54.36 | 25.67 | FI | 54.10 | 25.40 |
| busy | CoinMarketCap | upper | 0.04073 | 4.073 | 0.01 | 1 | 0.04073 | 58.86 | 31.42 | FI | 58.86 | 31.42 |
| busy | CoinMarketCap | facilitator | 0.04073 | 4.073 | 0.01 | 32 | 0.4592 | 70.15 | 41.45 | FI | 69.88 | 41.19 |
| busy | StableApify | lower | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 36.08 | 19.24 | FI | 36.08 | 19.24 |
| busy | StableApify | upper | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 36.20 | 20.07 | FI | 36.20 | 20.07 |
| busy | StableApify | facilitator | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 46.21 | 29.36 | FI | 46.21 | 29.36 |
| busy | Exa(0.001 or less) | lower | 0.001205 | 1.205 | 0.001 | 32 | 0.002474 | 1598.99 | 333.30 | FI | 1598.99 | 333.30 |
| busy | Exa(0.001 or less) | upper | 0.001205 | 1.205 | 0.001 | 1 | 0.001205 | 1690.10 | 436.23 | FI | 1690.10 | 436.23 |
| busy | Exa(0.001 or less) | facilitator | 0.001205 | 1.205 | 0.001 | 32 | 0.002474 | 1780.81 | 515.11 | FI | 1780.81 | 515.11 |
| busy | CoinStats(0.01 or less) | lower | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 548.85 | 220.28 | FI | 548.85 | 220.28 |
| busy | CoinStats(0.01 or less) | upper | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 552.67 | 229.09 | FI | 552.67 | 229.09 |
| busy | CoinStats(0.01 or less) | facilitator | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 659.55 | 330.98 | FI | 659.55 | 330.98 |
| busy | BlockRun | lower | 34.97 | 3206 | 0.01091 | 8 | 278.7 | 48.26 | 13.21 | FI | 48.50 | 24.31 |
| busy | BlockRun | upper | 34.97 | 3206 | 0.01091 | 1 | 34.97 | 48.30 | 14.40 | FI | 48.54 | 25.50 |
| busy | BlockRun | facilitator | 34.97 | 3206 | 0.01091 | 8 | 278.7 | 61.81 | 26.76 | FI | 62.05 | 37.86 |
| median | StableEnrich(Out candidates excluded) | lower | 0.521 | 14.34 | 0.03632 | 8 | 3.002 | 7.59 | 7.17 | FI | 7.45 | 7.03 |
| median | StableEnrich(Out candidates excluded) | upper | 0.521 | 14.34 | 0.03632 | 1 | 0.521 | 7.87 | 7.77 | FI | 7.85 | 7.75 |
| median | StableEnrich(Out candidates excluded) | facilitator | 0.521 | 14.34 | 0.03632 | 8 | 3.002 | 11.74 | 11.32 | FI | 11.60 | 11.18 |
| median | OneSource | lower | 0.07069 | 19.94 | 0.003545 | 4 | 0.1074 | 61.58 | 427.90 | FairBind | 59.21 | 71.00 |
| median | OneSource | upper | 0.07069 | 19.94 | 0.003545 | 1 | 0.07069 | 62.80 | 513.66 | FairBind | 61.25 | 76.65 |
| median | OneSource | facilitator | 0.07069 | 19.94 | 0.003545 | 4 | 0.1074 | 103.84 | 470.16 | FairBind | 101.48 | 113.26 |
| median | CoinMarketCap | lower | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 79.95 | 32.46 | FI | 79.95 | 32.46 |
| median | CoinMarketCap | upper | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 80.13 | 33.75 | FI | 80.13 | 33.75 |
| median | CoinMarketCap | facilitator | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 96.19 | 48.70 | FI | 96.19 | 48.70 |
| median | StableApify | lower | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 93.24 | 30.71 | FI | 93.24 | 30.71 |
| median | StableApify | upper | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 93.67 | 31.82 | FI | 93.67 | 31.82 |
| median | StableApify | facilitator | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 107.78 | 45.25 | FI | 107.78 | 45.25 |
| median | Exa(0.001 or less) | lower | 0.001214 | 1.214 | 0.001 | 32 | 0.002811 | 1595.37 | 339.72 | FI | 1578.71 | 323.05 |
| median | Exa(0.001 or less) | upper | 0.001214 | 1.214 | 0.001 | 1 | 0.001214 | 1678.70 | 435.00 | FI | 1678.70 | 435.00 |
| median | Exa(0.001 or less) | facilitator | 0.001214 | 1.214 | 0.001 | 32 | 0.002811 | 1776.95 | 521.29 | FI | 1760.28 | 504.63 |
| median | CoinStats(0.01 or less) | lower | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 882.92 | 330.88 | FI | 882.92 | 330.88 |
| median | CoinStats(0.01 or less) | upper | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 891.89 | 343.80 | FI | 891.89 | 343.80 |
| median | CoinStats(0.01 or less) | facilitator | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 1046.82 | 494.78 | FI | 1046.82 | 494.78 |
| median | BlockRun | lower | 42.3 | 1098 | 0.03853 | 8 | 338.4 | 35.42 | 3.87 | FI | 46.03 | 7.01 |
| median | BlockRun | upper | 42.3 | 1098 | 0.03853 | 1 | 42.3 | 35.45 | 4.21 | FI | 46.07 | 7.35 |
| median | BlockRun | facilitator | 42.3 | 1098 | 0.03853 | 8 | 338.4 | 39.26 | 7.70 | FI | 49.87 | 10.84 |
| quiet | StableEnrich(Out candidates excluded) | lower | 0.5653 | 21.69 | 0.02607 | 32 | 10.68 | 9.17 | 10.32 | FairBind | 8.50 | 9.75 |
| quiet | StableEnrich(Out candidates excluded) | upper | 0.5653 | 21.69 | 0.02607 | 1 | 0.5653 | 9.56 | 11.18 | FairBind | 8.83 | 10.54 |
| quiet | StableEnrich(Out candidates excluded) | facilitator | 0.5653 | 21.69 | 0.02607 | 32 | 10.68 | 14.91 | 16.07 | FairBind | 14.24 | 15.49 |
| quiet | OneSource | lower | 0.09259 | 15.34 | 0.006037 | 4 | 0.09311 | 42.08 | 252.44 | FairBind | 39.11 | 41.76 |
| quiet | OneSource | upper | 0.09259 | 15.34 | 0.006037 | 1 | 0.09259 | 42.41 | 302.29 | FairBind | 40.86 | 45.62 |
| quiet | OneSource | facilitator | 0.09259 | 15.34 | 0.006037 | 4 | 0.09311 | 67.00 | 277.36 | FairBind | 64.04 | 66.69 |
| quiet | CoinMarketCap | lower | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 134.03 | 38.52 | FI | 134.03 | 38.52 |
| quiet | CoinMarketCap | upper | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 134.32 | 39.81 | FI | 134.32 | 39.81 |
| quiet | CoinMarketCap | facilitator | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 151.44 | 55.93 | FI | 151.44 | 55.93 |
| quiet | StableApify | lower | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 133.09 | 40.22 | FI | 133.09 | 40.22 |
| quiet | StableApify | upper | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 134.16 | 41.62 | FI | 134.16 | 41.62 |
| quiet | StableApify | facilitator | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 151.66 | 58.79 | FI | 151.66 | 58.79 |
| quiet | Exa(0.001 or less) | lower | 0.001 | 1 | 0.001 | 32 | 0.002618 | 1879.21 | 328.59 | FI | 1879.21 | 328.59 |
| quiet | Exa(0.001 or less) | upper | 0.001 | 1 | 0.001 | 1 | 0.001 | 2011.37 | 472.23 | FI | 2011.37 | 472.23 |
| quiet | Exa(0.001 or less) | facilitator | 0.001 | 1 | 0.001 | 32 | 0.002618 | 2068.01 | 517.39 | FI | 2068.01 | 517.39 |
| quiet | CoinStats(0.01 or less) | lower | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 673.13 | 305.47 | FI | 673.13 | 305.47 |
| quiet | CoinStats(0.01 or less) | upper | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 695.93 | 318.39 | FI | 695.93 | 318.39 |
| quiet | CoinStats(0.01 or less) | facilitator | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 832.11 | 464.44 | FI | 832.11 | 464.44 |
| quiet | BlockRun | lower | 2.268 | 22.95 | 0.0988 | 32 | 41.72 | 3.91 | 1.63 | FI | 4.06 | 2.70 |
| quiet | BlockRun | upper | 2.268 | 22.95 | 0.0988 | 1 | 2.268 | 4.02 | 1.85 | FI | 4.16 | 2.90 |
| quiet | BlockRun | facilitator | 2.268 | 22.95 | 0.0988 | 32 | 41.72 | 5.42 | 3.15 | FI | 5.57 | 4.22 |

closed form seller own input applied values all in cells P9 and equal(upper reproduction). stylised curve(same R_e, v̄, activity ratio d, per epoch same sales count) value P9 and 0.05%p within cell 34 / 63. difference per epoch sales count not chosen not(anchor unit, release branch) and k11b E_k from the rule comes.


## 3. before payee region (tier 1a proof, per epoch sales count epochs, n_s values)

aggregate quiet window s1b(CDP) data 9/22 one day form, so(F/data-review/target_sellers_all_README.md 5 (line)) k11b quiet window(s1c) and differs. for reference only shown. busy window and median window name with seller n and R k11b and equal(`agg_match`).

(a) FairBind cheaper or equal and 10% or less, (b) FI cheaper and 10% or less, (c) two c 10% over(in parentheses: its among FairBind cheaper count / FI cheaper count).

| case | set | window | payee | revenue | (a) count | (a) revenue share | (b) count | (b) revenue share | (c) count | (c) revenue share |
|---|---|---|---|---|---|---|---|---|---|---|
| lower | Base(0x) payee | busy | 3392 | 235289.16 | 60 | 27.50 | 701 | 14.87 | 2631 (20 / 2611) | 57.63 |
| lower | Base(0x) payee | median | 18687 | 484196.10 | 76 | 20.08 | 985 | 71.13 | 17626 (15 / 17611) | 8.79 |
| lower | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 41 | 72.16 | 98 | 5.27 | 387 (13 / 374) | 22.57 |
| lower | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 4 | 1.16 | 534 | 16.86 | 2631 (20 / 2611) | 81.98 |
| lower | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 9 | 0.25 | 746 | 82.80 | 17626 (15 / 17611) | 16.94 |
| lower | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 4 | 0.54 | 73 | 14.47 | 387 (13 / 374) | 84.99 |
| lower | all payee(0x not address included) | busy | 5651 | 393066.34 | 95 | 21.20 | 2777 | 43.97 | 2779 (26 / 2753) | 34.83 |
| lower | all payee(0x not address included) | median | 20466 | 582603.80 | 89 | 31.36 | 2403 | 60.97 | 17974 (23 / 17951) | 7.66 |
| lower | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 51 | 76.87 | 254 | 14.83 | 591 (22 / 569) | 8.30 |
| upper | Base(0x) payee | busy | 3392 | 235289.16 | 60 | 27.49 | 696 | 14.86 | 2636 (22 / 2614) | 57.65 |
| upper | Base(0x) payee | median | 18687 | 484196.10 | 78 | 20.18 | 977 | 71.02 | 17632 (19 / 17613) | 8.79 |
| upper | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 42 | 72.19 | 94 | 5.23 | 390 (15 / 375) | 22.58 |
| upper | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 5 | 1.16 | 528 | 16.84 | 2636 (22 / 2614) | 82.01 |
| upper | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 11 | 0.45 | 738 | 82.59 | 17632 (19 / 17613) | 16.96 |
| upper | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 5 | 0.67 | 69 | 14.31 | 390 (15 / 375) | 85.02 |
| upper | all payee(0x not address included) | busy | 5651 | 393066.34 | 95 | 21.20 | 2770 | 43.96 | 2786 (28 / 2758) | 34.84 |
| upper | all payee(0x not address included) | median | 20466 | 582603.80 | 91 | 31.45 | 2394 | 60.89 | 17981 (27 / 17954) | 7.67 |
| upper | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 51 | 76.77 | 249 | 14.91 | 596 (24 / 572) | 8.32 |
| facilitator | Base(0x) payee | busy | 3392 | 235289.16 | 58 | 26.87 | 519 | 14.69 | 2815 (22 / 2793) | 58.44 |
| facilitator | Base(0x) payee | median | 18687 | 484196.10 | 73 | 20.00 | 846 | 44.41 | 17768 (18 / 17750) | 35.59 |
| facilitator | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 39 | 72.02 | 78 | 5.26 | 409 (15 / 394) | 22.72 |
| facilitator | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 2 | 0.26 | 352 | 16.61 | 2815 (22 / 2793) | 83.13 |
| facilitator | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 6 | 0.09 | 607 | 31.29 | 17768 (18 / 17750) | 68.61 |
| facilitator | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 2 | 0.04 | 53 | 14.42 | 409 (15 / 394) | 85.54 |
| facilitator | all payee(0x not address included) | busy | 5651 | 393066.34 | 92 | 20.79 | 1767 | 43.78 | 3792 (29 / 3763) | 35.43 |
| facilitator | all payee(0x not address included) | median | 20466 | 582603.80 | 84 | 30.73 | 1528 | 38.53 | 18854 (28 / 18826) | 30.75 |
| facilitator | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 48 | 76.74 | 218 | 14.78 | 630 (25 / 605) | 8.48 |

## 4. fill margin (fill cost / epoch revenue)

fee 0.005 / 0.0100 / 0.0161 gwei. mean R / E0, max window within profile epoch revenue maximum(*: payee whole value, so endpoint partial upper bound; quiet window aggregate k11b data differ left empty). class most low fee(0.005 gwei) <1, 1~10, >=10.


### swap proof window, most short admission length(T_sw = 31, to fill block 62)

fill cost USD: 297.78 / 595.56 / 958.85.

| window | seller | R_e mean | R_e max | margin(mean) | margin(max) | class(mean, 0.005) | class(max, 0.005) |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 0.7131 | 58.03* | 417.6 / 835.2 / 1345 | 5.131 / 10.26 / 16.52 | >=10 | 1~10 |
| busy | OneSource | 0.1212 | 1.266 | 2457 / 4914 / 7911 | 235.2 / 470.4 / 757.4 | >=10 | >=10 |
| busy | CoinMarketCap | 0.04073 | 0.47 | 7311 / 1.462e+04 / 2.354e+04 | 633.6 / 1267 / 2040 | >=10 | >=10 |
| busy | StableApify | 0.06807 | 0.56 | 4375 / 8749 / 1.409e+04 | 531.7 / 1063 / 1712 | >=10 | >=10 |
| busy | Exa(0.001 or less) | 0.001205 | 0.49* | 2.471e+05 / 4.942e+05 / 7.956e+05 | 607.7 / 1215 / 1957 | >=10 | >=10 |
| busy | CoinStats(0.01 or less) | 0.004125 | 0.309* | 7.219e+04 / 1.444e+05 / 2.324e+05 | 963.7 / 1927 / 3103 | >=10 | >=10 |
| busy | BlockRun | 34.97 | 149.5 | 8.515 / 17.03 / 27.42 | 1.992 / 3.984 / 6.415 | 1~10 | 1~10 |
| median | StableEnrich(Out candidates excluded) | 0.521 | 31.51* | 571.6 / 1143 / 1841 | 9.45 / 18.9 / 30.43 | >=10 | 1~10 |
| median | OneSource | 0.07069 | 0.394 | 4212 / 8425 / 1.356e+04 | 755.8 / 1512 / 2434 | >=10 | >=10 |
| median | CoinMarketCap | 0.0281 | 0.25 | 1.06e+04 / 2.119e+04 / 3.412e+04 | 1191 / 2382 / 3835 | >=10 | >=10 |
| median | StableApify | 0.02315 | 0.1 | 1.286e+04 / 2.573e+04 / 4.142e+04 | 2978 / 5956 / 9588 | >=10 | >=10 |
| median | Exa(0.001 or less) | 0.001214 | 0.98* | 2.454e+05 / 4.907e+05 / 7.901e+05 | 303.9 / 607.7 / 978.4 | >=10 | >=10 |
| median | CoinStats(0.01 or less) | 0.002545 | 0.044* | 1.17e+05 / 2.34e+05 / 3.767e+05 | 6768 / 1.354e+04 / 2.179e+04 | >=10 | >=10 |
| median | BlockRun | 42.3 | 856.9 | 7.04 / 14.08 / 22.67 | 0.3475 / 0.695 / 1.119 | 1~10 | <1 |
| quiet | StableEnrich(Out candidates excluded) | 0.5653 | -* | 526.7 / 1053 / 1696 | - / - / - | >=10 | - |
| quiet | OneSource | 0.09259 | - | 3216 / 6432 / 1.036e+04 | - / - / - | >=10 | - |
| quiet | CoinMarketCap | 0.01557 | - | 1.912e+04 / 3.824e+04 / 6.157e+04 | - / - / - | >=10 | - |
| quiet | StableApify | 0.016 | - | 1.861e+04 / 3.722e+04 / 5.993e+04 | - / - / - | >=10 | - |
| quiet | Exa(0.001 or less) | 0.001 | -* | 2.978e+05 / 5.956e+05 / 9.588e+05 | - / - / - | >=10 | - |
| quiet | CoinStats(0.01 or less) | 0.003667 | -* | 8.121e+04 / 1.624e+05 / 2.615e+05 | - / - / - | >=10 | - |
| quiet | BlockRun | 2.268 | - | 131.3 / 262.6 / 422.9 | - / - / - | >=10 | - |

### swap proof window T_sw = 300(to fill block 331)

fill cost USD: 1589.75 / 3179.51 / 5119.01.

| window | seller | R_e mean | R_e max | margin(mean) | margin(max) | class(mean, 0.005) | class(max, 0.005) |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 0.7131 | 58.03* | 2230 / 4459 / 7179 | 27.4 / 54.79 / 88.21 | >=10 | >=10 |
| busy | OneSource | 0.1212 | 1.266 | 1.312e+04 / 2.623e+04 / 4.224e+04 | 1256 / 2511 / 4043 | >=10 | >=10 |
| busy | CoinMarketCap | 0.04073 | 0.47 | 3.903e+04 / 7.807e+04 / 1.257e+05 | 3382 / 6765 / 1.089e+04 | >=10 | >=10 |
| busy | StableApify | 0.06807 | 0.56 | 2.336e+04 / 4.671e+04 / 7.52e+04 | 2839 / 5678 / 9141 | >=10 | >=10 |
| busy | Exa(0.001 or less) | 0.001205 | 0.49* | 1.319e+06 / 2.638e+06 / 4.248e+06 | 3244 / 6489 / 1.045e+04 | >=10 | >=10 |
| busy | CoinStats(0.01 or less) | 0.004125 | 0.309* | 3.854e+05 / 7.708e+05 / 1.241e+06 | 5145 / 1.029e+04 / 1.657e+04 | >=10 | >=10 |
| busy | BlockRun | 34.97 | 149.5 | 45.46 / 90.91 / 146.4 | 10.64 / 21.27 / 34.25 | >=10 | >=10 |
| median | StableEnrich(Out candidates excluded) | 0.521 | 31.51* | 3052 / 6103 / 9826 | 50.45 / 100.9 / 162.5 | >=10 | >=10 |
| median | OneSource | 0.07069 | 0.394 | 2.249e+04 / 4.498e+04 / 7.241e+04 | 4035 / 8070 / 1.299e+04 | >=10 | >=10 |
| median | CoinMarketCap | 0.0281 | 0.25 | 5.657e+04 / 1.131e+05 / 1.821e+05 | 6359 / 1.272e+04 / 2.048e+04 | >=10 | >=10 |
| median | StableApify | 0.02315 | 0.1 | 6.868e+04 / 1.374e+05 / 2.211e+05 | 1.59e+04 / 3.18e+04 / 5.119e+04 | >=10 | >=10 |
| median | Exa(0.001 or less) | 0.001214 | 0.98* | 1.31e+06 / 2.62e+06 / 4.218e+06 | 1622 / 3244 / 5223 | >=10 | >=10 |
| median | CoinStats(0.01 or less) | 0.002545 | 0.044* | 6.245e+05 / 1.249e+06 / 2.011e+06 | 3.613e+04 / 7.226e+04 / 1.163e+05 | >=10 | >=10 |
| median | BlockRun | 42.3 | 856.9 | 37.59 / 75.17 / 121 | 1.855 / 3.71 / 5.974 | >=10 | 1~10 |
| quiet | StableEnrich(Out candidates excluded) | 0.5653 | -* | 2812 / 5624 / 9055 | - / - / - | >=10 | - |
| quiet | OneSource | 0.09259 | - | 1.717e+04 / 3.434e+04 / 5.528e+04 | - / - / - | >=10 | - |
| quiet | CoinMarketCap | 0.01557 | - | 1.021e+05 / 2.042e+05 / 3.287e+05 | - / - / - | >=10 | - |
| quiet | StableApify | 0.016 | - | 9.936e+04 / 1.987e+05 / 3.199e+05 | - / - / - | >=10 | - |
| quiet | Exa(0.001 or less) | 0.001 | -* | 1.59e+06 / 3.18e+06 / 5.119e+06 | - / - / - | >=10 | - |
| quiet | CoinStats(0.01 or less) | 0.003667 | -* | 4.336e+05 / 8.671e+05 / 1.396e+06 | - / - / - | >=10 | - |
| quiet | BlockRun | 2.268 | - | 701.1 / 1402 / 2258 | - / - / - | >=10 | - |

### evaluation profile(swap proof window proof deadline and together ends, P5 1,800 block)

fill cost USD: 8645.18 / 17290.37 / 27837.49.

| window | seller | R_e mean | R_e max | margin(mean) | margin(max) | class(mean, 0.005) | class(max, 0.005) |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 0.7131 | 58.03* | 1.212e+04 / 2.425e+04 / 3.904e+04 | 149 / 298 / 479.7 | >=10 | >=10 |
| busy | OneSource | 0.1212 | 1.266 | 7.133e+04 / 1.427e+05 / 2.297e+05 | 6829 / 1.366e+04 / 2.199e+04 | >=10 | >=10 |
| busy | CoinMarketCap | 0.04073 | 0.47 | 2.123e+05 / 4.245e+05 / 6.835e+05 | 1.839e+04 / 3.679e+04 / 5.923e+04 | >=10 | >=10 |
| busy | StableApify | 0.06807 | 0.56 | 1.27e+05 / 2.54e+05 / 4.09e+05 | 1.544e+04 / 3.088e+04 / 4.971e+04 | >=10 | >=10 |
| busy | Exa(0.001 or less) | 0.001205 | 0.49* | 7.174e+06 / 1.435e+07 / 2.31e+07 | 1.764e+04 / 3.529e+04 / 5.681e+04 | >=10 | >=10 |
| busy | CoinStats(0.01 or less) | 0.004125 | 0.309* | 2.096e+06 / 4.192e+06 / 6.748e+06 | 2.798e+04 / 5.596e+04 / 9.009e+04 | >=10 | >=10 |
| busy | BlockRun | 34.97 | 149.5 | 247.2 / 494.4 / 796 | 57.84 / 115.7 / 186.2 | >=10 | >=10 |
| median | StableEnrich(Out candidates excluded) | 0.521 | 31.51* | 1.659e+04 / 3.319e+04 / 5.343e+04 | 274.4 / 548.7 / 883.4 | >=10 | >=10 |
| median | OneSource | 0.07069 | 0.394 | 1.223e+05 / 2.446e+05 / 3.938e+05 | 2.194e+04 / 4.388e+04 / 7.065e+04 | >=10 | >=10 |
| median | CoinMarketCap | 0.0281 | 0.25 | 3.076e+05 / 6.152e+05 / 9.905e+05 | 3.458e+04 / 6.916e+04 / 1.113e+05 | >=10 | >=10 |
| median | StableApify | 0.02315 | 0.1 | 3.735e+05 / 7.469e+05 / 1.203e+06 | 8.645e+04 / 1.729e+05 / 2.784e+05 | >=10 | >=10 |
| median | Exa(0.001 or less) | 0.001214 | 0.98* | 7.123e+06 / 1.425e+07 / 2.294e+07 | 8822 / 1.764e+04 / 2.841e+04 | >=10 | >=10 |
| median | CoinStats(0.01 or less) | 0.002545 | 0.044* | 3.396e+06 / 6.793e+06 / 1.094e+07 | 1.965e+05 / 3.93e+05 / 6.327e+05 | >=10 | >=10 |
| median | BlockRun | 42.3 | 856.9 | 204.4 / 408.8 / 658.2 | 10.09 / 20.18 / 32.49 | >=10 | >=10 |
| quiet | StableEnrich(Out candidates excluded) | 0.5653 | -* | 1.529e+04 / 3.059e+04 / 4.924e+04 | - / - / - | >=10 | - |
| quiet | OneSource | 0.09259 | - | 9.337e+04 / 1.867e+05 / 3.006e+05 | - / - / - | >=10 | - |
| quiet | CoinMarketCap | 0.01557 | - | 5.551e+05 / 1.11e+06 / 1.787e+06 | - / - / - | >=10 | - |
| quiet | StableApify | 0.016 | - | 5.403e+05 / 1.081e+06 / 1.74e+06 | - / - / - | >=10 | - |
| quiet | Exa(0.001 or less) | 0.001 | -* | 8.645e+06 / 1.729e+07 / 2.784e+07 | - / - / - | >=10 | - |
| quiet | CoinStats(0.01 or less) | 0.003667 | -* | 2.358e+06 / 4.716e+06 / 7.592e+06 | - / - / - | >=10 | - |
| quiet | BlockRun | 2.268 | - | 3813 / 7625 / 1.228e+04 | - / - / - | >=10 | - |

### reference only: anchor window a_A = 120(P8 D1)

fill cost USD: 576.35 / 1152.69 / 1855.83.

| window | seller | R_e mean | R_e max | margin(mean) | margin(max) | class(mean, 0.005) | class(max, 0.005) |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | 0.7131 | 58.03* | 808.3 / 1617 / 2603 | 9.932 / 19.86 / 31.98 | >=10 | 1~10 |
| busy | OneSource | 0.1212 | 1.266 | 4755 / 9511 / 1.531e+04 | 455.2 / 910.5 / 1466 | >=10 | >=10 |
| busy | CoinMarketCap | 0.04073 | 0.47 | 1.415e+04 / 2.83e+04 / 4.557e+04 | 1226 / 2453 / 3949 | >=10 | >=10 |
| busy | StableApify | 0.06807 | 0.56 | 8467 / 1.693e+04 / 2.726e+04 | 1029 / 2058 / 3314 | >=10 | >=10 |
| busy | Exa(0.001 or less) | 0.001205 | 0.49* | 4.782e+05 / 9.565e+05 / 1.54e+06 | 1176 / 2352 / 3787 | >=10 | >=10 |
| busy | CoinStats(0.01 or less) | 0.004125 | 0.309* | 1.397e+05 / 2.794e+05 / 4.499e+05 | 1865 / 3730 / 6006 | >=10 | >=10 |
| busy | BlockRun | 34.97 | 149.5 | 16.48 / 32.96 / 53.07 | 3.856 / 7.711 / 12.42 | >=10 | 1~10 |
| median | StableEnrich(Out candidates excluded) | 0.521 | 31.51* | 1106 / 2213 / 3562 | 18.29 / 36.58 / 58.9 | >=10 | >=10 |
| median | OneSource | 0.07069 | 0.394 | 8153 / 1.631e+04 / 2.625e+04 | 1463 / 2926 / 4710 | >=10 | >=10 |
| median | CoinMarketCap | 0.0281 | 0.25 | 2.051e+04 / 4.102e+04 / 6.604e+04 | 2305 / 4611 / 7423 | >=10 | >=10 |
| median | StableApify | 0.02315 | 0.1 | 2.49e+04 / 4.98e+04 / 8.017e+04 | 5763 / 1.153e+04 / 1.856e+04 | >=10 | >=10 |
| median | Exa(0.001 or less) | 0.001214 | 0.98* | 4.749e+05 / 9.498e+05 / 1.529e+06 | 588.1 / 1176 / 1894 | >=10 | >=10 |
| median | CoinStats(0.01 or less) | 0.002545 | 0.044* | 2.264e+05 / 4.528e+05 / 7.291e+05 | 1.31e+04 / 2.62e+04 / 4.218e+04 | >=10 | >=10 |
| median | BlockRun | 42.3 | 856.9 | 13.63 / 27.25 / 43.88 | 0.6726 / 1.345 / 2.166 | >=10 | <1 |
| quiet | StableEnrich(Out candidates excluded) | 0.5653 | -* | 1020 / 2039 / 3283 | - / - / - | >=10 | - |
| quiet | OneSource | 0.09259 | - | 6224 / 1.245e+04 / 2.004e+04 | - / - / - | >=10 | - |
| quiet | CoinMarketCap | 0.01557 | - | 3.701e+04 / 7.401e+04 / 1.192e+05 | - / - / - | >=10 | - |
| quiet | StableApify | 0.016 | - | 3.602e+04 / 7.204e+04 / 1.16e+05 | - / - / - | >=10 | - |
| quiet | Exa(0.001 or less) | 0.001 | -* | 5.763e+05 / 1.153e+06 / 1.856e+06 | - / - / - | >=10 | - |
| quiet | CoinStats(0.01 or less) | 0.003667 | -* | 1.572e+05 / 3.144e+05 / 5.061e+05 | - / - / - | >=10 | - |
| quiet | BlockRun | 2.268 | - | 254.2 / 508.3 / 818.4 | - / - / - | >=10 | - |
