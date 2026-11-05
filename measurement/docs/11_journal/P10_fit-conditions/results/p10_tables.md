**all values post hoc calculations registered verdict none.** `p10.py` output. P9 V1(measured VRF, release, anchor), mode N, σ 1, r 10%, a 0, w 0.00173, V 1, per seller optimal k. costs revenue relative to %, R_e active profile per epoch revenue(USDC).

reproduction(`--check`): observed seller closed form vs p9.json V1 max difference FairBind 2.2e-14%p, FI 0.0e+00%p, k mismatch 0; stylised seller vs P9 Env max difference 0.0e+00%p, k mismatch 0. admission 0.05%p.

## 1. threshold (stylised seller, 21 days window, tier 1a proof)

R_e USDC, in parentheses sales count m and then k. "below" cost share threshold below entering R_e, "upper" freeze term because again over R_e. FI crossing two design cost share equalizing R_e(→ after its above more cheaper side).

| case | d | v̄ | 10% below | 10% upper | 5% below | 5% upper | min cost share | FI crossing |
|---|---|---|---|---|---|---|---|---|
| lower | 1 | 0.001 | none | none | none | none | 128.94 | 0.01325 → FB |
| lower | 0.1 | 0.001 | none | none | none | none | 128.41 | 0.01326 → FB |
| lower | 1 | 0.002 | none | none | none | none | 65.25 | 0.02655 → FB; 87.82 → FI |
| lower | 0.1 | 0.002 | none | none | none | none | 64.68 | 0.02656 → FB; 880.5 → FI |
| lower | 1 | 0.005 | none | none | none | none | 27.66 | 0.0669 → FB; 24.17 → FI |
| lower | 0.1 | 0.005 | none | none | none | none | 26.22 | 0.06676 → FB; 243.6 → FI |
| lower | 1 | 0.01 | none | none | none | none | 15.49 | 0.1364 → FB; 10.74 → FI |
| lower | 0.1 | 0.01 | none | none | none | none | 13.54 | 0.1348 → FB; 111 → FI |
| lower | 1 | 0.02 | 0.6108 (m 30.54, k 8) | 2.146 (m 107.3, k 2) | none | none | 9.41 | 0.2914 → FB; 4.569 → FI |
| lower | 0.1 | 0.02 | 0.5305 (m 26.53, k 1) | 24.32 (m 1216, k 16) | none | none | 7.41 | 0.2753 → FB; 52.08 → FI |
| lower | 1 | 0.05 | 0.2444 (m 4.888, k 32) | 5.489 (m 109.8, k 2) | none | none | 5.76 | none(increase FI) |
| lower | 0.1 | 0.05 | 0.2421 (m 4.842, k 32) | 55.99 (m 1120, k 2) | 0.8918 (m 17.84, k 1) | 13.36 (m 267.1, k 32) | 3.78 | 0.7527 → FB; 17.65 → FI |
| lower | 1 | 0.1 | 0.2066 (m 2.066, k 32) | 6.539 (m 65.39, k 2) | 0.6589 (m 6.589, k 32) | 1.994 (m 19.94, k 8) | 4.54 | none(increase FI) |
| lower | 0.1 | 0.1 | 0.207 (m 2.07, k 32) | 66.68 (m 666.8, k 4) | 0.5199 (m 5.199, k 32) | 25.6 (m 256, k 1) | 2.57 | 2.149 → FB; 6.051 → FI |
| lower | 1 | 0.2 | from the start below | 7.07 (m 35.35, k 4) | 0.5002 (m 2.501, k 32) | 2.642 (m 13.21, k 16) | 3.94 | none(increase FI) |
| lower | 0.1 | 0.2 | from the start below | 72.06 (m 360.3, k 2) | 0.4389 (m 2.194, k 32) | 31.11 (m 155.6, k 1) | 1.96 | none(increase FI) |
| lower | 1 | 0.5 | from the start below | 7.388 (m 14.78, k 16) | from the start below | 2.992 (m 5.984, k 16) | 3.57 | none(increase FI) |
| lower | 0.1 | 0.5 | from the start below | 75.73 (m 151.5, k 1) | from the start below | 34.07 (m 68.15, k 1) | 1.58 | none(increase FI) |
| lower | 1 | 1 | from the start below | 7.493 (m 7.493, k 8) | from the start below | 3.105 (m 3.105, k 16) | 3.45 | none(increase FI) |
| lower | 0.1 | 1 | from the start below | 76.77 (m 76.77, k 1) | from the start below | 35.06 (m 35.06, k 1) | 1.46 | none(increase FI) |
| upper | 1 | 0.001 | none | none | none | none | 128.97 | 0.01202 → FB |
| upper | 0.1 | 0.001 | none | none | none | none | 128.45 | 0.01204 → FB |
| upper | 1 | 0.002 | none | none | none | none | 65.28 | 0.02409 → FB; 105.1 → FI |
| upper | 0.1 | 0.002 | none | none | none | none | 64.71 | 0.02412 → FB; 1054 → FI |
| upper | 1 | 0.005 | none | none | none | none | 27.69 | 0.06069 → FB; 26.9 → FI |
| upper | 0.1 | 0.005 | none | none | none | none | 26.25 | 0.06062 → FB; 271.2 → FI |
| upper | 1 | 0.01 | none | none | none | none | 15.60 | 0.1235 → FB; 11.92 → FI |
| upper | 0.1 | 0.01 | none | none | none | none | 13.57 | 0.1224 → FB; 122.4 → FI |
| upper | 1 | 0.02 | 0.7065 (m 35.32, k 1) | 2.061 (m 103, k 1) | none | none | 9.55 | 0.2617 → FB; 5.106 → FI |
| upper | 0.1 | 0.02 | 0.5355 (m 26.77, k 1) | 24.03 (m 1201, k 1) | none | none | 7.44 | 0.2501 → FB; 57.25 → FI |
| upper | 1 | 0.05 | 0.2723 (m 5.447, k 1) | 5.448 (m 109, k 1) | none | none | 5.92 | none(increase FI) |
| upper | 0.1 | 0.05 | 0.2605 (m 5.21, k 1) | 55.71 (m 1114, k 1) | 0.9062 (m 18.12, k 1) | 12.8 (m 256, k 1) | 3.81 | 0.6805 → FB; 19.71 → FI |
| upper | 1 | 0.1 | 0.2297 (m 2.297, k 1) | 6.501 (m 65.01, k 1) | 0.7852 (m 7.852, k 1) | 1.852 (m 18.52, k 1) | 4.71 | none(increase FI) |
| upper | 0.1 | 0.1 | 0.2226 (m 2.226, k 1) | 66.42 (m 664.2, k 1) | 0.5624 (m 5.624, k 1) | 25.6 (m 256, k 1) | 2.60 | 1.82 → FB; 7.152 → FI |
| upper | 1 | 0.2 | 0.2132 (m 1.066, k 1) | 7.027 (m 35.14, k 1) | 0.5725 (m 2.862, k 1) | 2.549 (m 12.74, k 1) | 4.11 | none(increase FI) |
| upper | 0.1 | 0.2 | 0.2075 (m 1.038, k 1) | 71.78 (m 358.9, k 1) | 0.474 (m 2.37, k 1) | 30.87 (m 154.3, k 1) | 2.00 | none(increase FI) |
| upper | 1 | 0.5 | from the start below | 7.344 (m 14.69, k 1) | 0.5023 (m 1.005, k 1) | 2.911 (m 5.821, k 1) | 3.75 | none(increase FI) |
| upper | 0.1 | 0.5 | from the start below | 75.47 (m 150.9, k 1) | from the start below | 33.83 (m 67.65, k 1) | 1.64 | none(increase FI) |
| upper | 1 | 1 | from the start below | 7.45 (m 7.45, k 1) | from the start below | 3.027 (m 3.027, k 1) | 3.63 | none(increase FI) |
| upper | 0.1 | 1 | from the start below | 76.51 (m 76.51, k 1) | from the start below | 34.82 (m 34.82, k 1) | 1.51 | none(increase FI) |
| facilitator | 1 | 0.001 | none | none | none | none | 276.89 | 0.01325 → FB |
| facilitator | 0.1 | 0.001 | none | none | none | none | 276.21 | 0.01326 → FB |
| facilitator | 1 | 0.002 | none | none | none | none | 139.23 | 0.02655 → FB; 87.82 → FI |
| facilitator | 0.1 | 0.002 | none | none | none | none | 138.66 | 0.02656 → FB; 880.5 → FI |
| facilitator | 1 | 0.005 | none | none | none | none | 57.26 | 0.0669 → FB; 24.17 → FI |
| facilitator | 0.1 | 0.005 | none | none | none | none | 55.81 | 0.06676 → FB; 243.6 → FI |
| facilitator | 1 | 0.01 | none | none | none | none | 30.31 | 0.1364 → FB; 10.74 → FI |
| facilitator | 0.1 | 0.01 | none | none | none | none | 28.33 | 0.1348 → FB; 111 → FI |
| facilitator | 1 | 0.02 | none | none | none | none | 16.83 | 0.2914 → FB; 4.569 → FI |
| facilitator | 0.1 | 0.02 | none | none | none | none | 14.81 | 0.2753 → FB; 52.08 → FI |
| facilitator | 1 | 0.05 | 0.4767 (m 9.535, k 16) | 2.843 (m 56.85, k 4) | none | none | 8.75 | none(increase FI) |
| facilitator | 0.1 | 0.05 | 0.4377 (m 8.754, k 16) | 31.31 (m 626.3, k 2) | none | none | 6.75 | 0.7527 → FB; 17.65 → FI |
| facilitator | 1 | 0.1 | 0.2614 (m 2.614, k 32) | 5.255 (m 52.55, k 4) | none | none | 6.06 | none(increase FI) |
| facilitator | 0.1 | 0.1 | 0.2575 (m 2.575, k 32) | 54.17 (m 541.7, k 4) | 1.02 (m 10.2, k 16) | 13.97 (m 139.7, k 1) | 4.06 | 2.149 → FB; 6.051 → FI |
| facilitator | 1 | 0.2 | 0.2155 (m 1.078, k 32) | 6.423 (m 32.11, k 4) | 0.748 (m 3.74, k 32) | 1.803 (m 9.013, k 16) | 4.71 | none(increase FI) |
| facilitator | 0.1 | 0.2 | 0.2154 (m 1.077, k 32) | 65.75 (m 328.8, k 2) | 0.5553 (m 2.776, k 32) | 25.07 (m 125.4, k 1) | 2.72 | none(increase FI) |
| facilitator | 1 | 0.5 | from the start below | 7.126 (m 14.25, k 16) | 0.5029 (m 1.006, k 32) | 2.693 (m 5.387, k 16) | 3.90 | none(increase FI) |
| facilitator | 0.1 | 0.5 | from the start below | 73.21 (m 146.4, k 1) | from the start below | 31.65 (m 63.3, k 1) | 1.88 | none(increase FI) |
| facilitator | 1 | 1 | from the start below | 7.36 (m 7.36, k 16) | from the start below | 2.953 (m 2.953, k 16) | 3.64 | none(increase FI) |
| facilitator | 0.1 | 1 | from the start below | 75.5 (m 75.5, k 1) | from the start below | 33.85 (m 33.85, k 1) | 1.62 | none(increase FI) |

### closed form, lower (freeze and capital without R_e* = c / (θ − a − b / v̄), d 1, m k ≤ 256, v̄ ≤ V; - θ ≤ a + b / v̄d threshold none)

| case | v̄ | k | θ | a | b (USDC/sales) | c (USDC/epoch) | R_e* |
|---|---|---|---|---|---|---|---|
| lower | 0.02 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01856 | 0.5194 |
| lower | 0.02 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01856 | - |
| lower | 0.02 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01697 | 0.4751 |
| lower | 0.02 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01697 | - |
| lower | 0.02 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01680 | 0.4703 |
| lower | 0.02 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01680 | - |
| lower | 0.05 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01856 | 0.2577 |
| lower | 0.05 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01856 | 0.8431 |
| lower | 0.05 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01697 | 0.2357 |
| lower | 0.05 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01697 | 0.7711 |
| lower | 0.05 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01680 | 0.2333 |
| lower | 0.05 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01680 | 0.7634 |
| lower | 0.1 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01856 | 0.2207 |
| lower | 0.1 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01856 | 0.5441 |
| lower | 0.1 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01697 | 0.2018 |
| lower | 0.1 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01697 | 0.4977 |
| lower | 0.1 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01680 | 0.1998 |
| lower | 0.1 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01680 | 0.4927 |
| lower | 0.2 | 1 | 0.1 | 0.00380 | 1.209e-03 | 0.01856 | 0.2059 |
| lower | 0.2 | 1 | 0.05 | 0.00380 | 1.209e-03 | 0.01856 | 0.4622 |
| lower | 0.2 | 8 | 0.1 | 0.00380 | 1.209e-03 | 0.01697 | 0.1883 |
| lower | 0.2 | 8 | 0.05 | 0.00380 | 1.209e-03 | 0.01697 | 0.4227 |
| lower | 0.2 | 32 | 0.1 | 0.00380 | 1.209e-03 | 0.01680 | 0.1864 |
| lower | 0.2 | 32 | 0.05 | 0.00380 | 1.209e-03 | 0.01680 | 0.4185 |

## 2. observed seller (V1, V 1)

| window | seller | case | R_e | m | v̄ | k* | R / E_k* | FairBind | FI | more cheaper side | stylised curve FairBind | stylised curve FI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | 0.7131 | 18.75 | 0.03802 | 4 | 1.93 | 6.74 | 6.89 | FairBind | 6.58 | 6.73 |
| busy | StableEnrich(Out candidates excluded) | upper | 0.7131 | 18.75 | 0.03802 | 1 | 0.7131 | 6.85 | 7.32 | FairBind | 6.82 | 7.28 |
| busy | StableEnrich(Out candidates excluded) | facilitator | 0.7131 | 18.75 | 0.03802 | 4 | 1.93 | 10.68 | 10.84 | FairBind | 10.53 | 10.68 |
| busy | OneSource | lower | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 45.46 | 353.24 | FairBind | 43.88 | 59.30 |
| busy | OneSource | upper | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 45.79 | 423.27 | FairBind | 43.92 | 62.31 |
| busy | OneSource | facilitator | 0.1212 | 28.21 | 0.004296 | 1 | 0.1212 | 80.20 | 387.98 | FairBind | 78.62 | 94.04 |
| busy | CoinMarketCap | lower | 0.04073 | 4.073 | 0.01 | 32 | 0.4592 | 54.29 | 25.60 | FI | 54.03 | 25.33 |
| busy | CoinMarketCap | upper | 0.04073 | 4.073 | 0.01 | 1 | 0.04073 | 58.11 | 30.67 | FI | 58.11 | 30.67 |
| busy | CoinMarketCap | facilitator | 0.04073 | 4.073 | 0.01 | 32 | 0.4592 | 70.08 | 41.38 | FI | 69.81 | 41.12 |
| busy | StableApify | lower | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 35.63 | 18.79 | FI | 35.63 | 18.79 |
| busy | StableApify | upper | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 35.75 | 19.62 | FI | 35.75 | 19.62 |
| busy | StableApify | facilitator | 0.06807 | 4.386 | 0.01552 | 1 | 0.06807 | 45.76 | 28.92 | FI | 45.76 | 28.92 |
| busy | Exa(0.001 or less) | lower | 0.001205 | 1.205 | 0.001 | 32 | 0.002474 | 1586.67 | 321.01 | FI | 1586.67 | 321.01 |
| busy | Exa(0.001 or less) | upper | 0.001205 | 1.205 | 0.001 | 1 | 0.001205 | 1664.84 | 411.00 | FI | 1664.84 | 411.00 |
| busy | Exa(0.001 or less) | facilitator | 0.001205 | 1.205 | 0.001 | 32 | 0.002474 | 1768.49 | 502.82 | FI | 1768.49 | 502.82 |
| busy | CoinStats(0.01 or less) | lower | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 541.47 | 212.90 | FI | 541.47 | 212.90 |
| busy | CoinStats(0.01 or less) | upper | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 545.29 | 221.71 | FI | 545.29 | 221.71 |
| busy | CoinStats(0.01 or less) | facilitator | 0.004125 | 2.812 | 0.001467 | 1 | 0.004125 | 652.17 | 323.61 | FI | 652.17 | 323.61 |
| busy | BlockRun | lower | 34.97 | 3206 | 0.01091 | 8 | 278.7 | 48.25 | 13.20 | FI | 48.49 | 24.30 |
| busy | BlockRun | upper | 34.97 | 3206 | 0.01091 | 1 | 34.97 | 48.29 | 14.39 | FI | 48.53 | 25.49 |
| busy | BlockRun | facilitator | 34.97 | 3206 | 0.01091 | 8 | 278.7 | 61.80 | 26.75 | FI | 62.04 | 37.85 |
| median | StableEnrich(Out candidates excluded) | lower | 0.521 | 14.34 | 0.03632 | 8 | 3.002 | 7.58 | 7.16 | FI | 7.45 | 7.02 |
| median | StableEnrich(Out candidates excluded) | upper | 0.521 | 14.34 | 0.03632 | 1 | 0.521 | 7.81 | 7.71 | FI | 7.79 | 7.69 |
| median | StableEnrich(Out candidates excluded) | facilitator | 0.521 | 14.34 | 0.03632 | 8 | 3.002 | 11.73 | 11.31 | FI | 11.59 | 11.17 |
| median | OneSource | lower | 0.07069 | 19.94 | 0.003545 | 4 | 0.1074 | 61.29 | 427.62 | FairBind | 59.07 | 70.86 |
| median | OneSource | upper | 0.07069 | 19.94 | 0.003545 | 1 | 0.07069 | 62.37 | 513.23 | FairBind | 60.82 | 76.22 |
| median | OneSource | facilitator | 0.07069 | 19.94 | 0.003545 | 4 | 0.1074 | 103.56 | 469.88 | FairBind | 101.34 | 113.12 |
| median | CoinMarketCap | lower | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 78.87 | 31.38 | FI | 78.87 | 31.38 |
| median | CoinMarketCap | upper | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 79.05 | 32.67 | FI | 79.05 | 32.67 |
| median | CoinMarketCap | facilitator | 0.0281 | 2.81 | 0.01 | 1 | 0.0281 | 95.11 | 47.62 | FI | 95.11 | 47.62 |
| median | StableApify | lower | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 91.93 | 29.39 | FI | 91.93 | 29.39 |
| median | StableApify | upper | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 92.36 | 30.51 | FI | 92.36 | 30.51 |
| median | StableApify | facilitator | 0.02315 | 2 | 0.01157 | 1 | 0.02315 | 106.47 | 43.93 | FI | 106.47 | 43.93 |
| median | Exa(0.001 or less) | lower | 0.001214 | 1.214 | 0.001 | 32 | 0.002811 | 1584.42 | 328.78 | FI | 1567.86 | 312.23 |
| median | Exa(0.001 or less) | upper | 0.001214 | 1.214 | 0.001 | 1 | 0.001214 | 1653.62 | 409.94 | FI | 1653.62 | 409.94 |
| median | Exa(0.001 or less) | facilitator | 0.001214 | 1.214 | 0.001 | 32 | 0.002811 | 1765.99 | 510.36 | FI | 1749.44 | 493.81 |
| median | CoinStats(0.01 or less) | lower | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 870.96 | 318.94 | FI | 870.96 | 318.94 |
| median | CoinStats(0.01 or less) | upper | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 879.93 | 331.86 | FI | 879.93 | 331.86 |
| median | CoinStats(0.01 or less) | facilitator | 0.002545 | 2.545 | 0.001 | 1 | 0.002545 | 1034.86 | 482.83 | FI | 1034.86 | 482.83 |
| median | BlockRun | lower | 42.3 | 1098 | 0.03853 | 8 | 338.4 | 35.42 | 3.86 | FI | 46.03 | 7.00 |
| median | BlockRun | upper | 42.3 | 1098 | 0.03853 | 1 | 42.3 | 35.44 | 4.20 | FI | 46.06 | 7.35 |
| median | BlockRun | facilitator | 42.3 | 1098 | 0.03853 | 8 | 338.4 | 39.25 | 7.70 | FI | 49.86 | 10.84 |
| quiet | StableEnrich(Out candidates excluded) | lower | 0.5653 | 21.69 | 0.02607 | 32 | 10.68 | 9.16 | 10.32 | FairBind | 8.49 | 9.74 |
| quiet | StableEnrich(Out candidates excluded) | upper | 0.5653 | 21.69 | 0.02607 | 1 | 0.5653 | 9.50 | 11.13 | FairBind | 8.77 | 10.49 |
| quiet | StableEnrich(Out candidates excluded) | facilitator | 0.5653 | 21.69 | 0.02607 | 32 | 10.68 | 14.90 | 16.06 | FairBind | 14.23 | 15.48 |
| quiet | OneSource | lower | 0.09259 | 15.34 | 0.006037 | 4 | 0.09311 | 41.75 | 252.11 | FairBind | 39.03 | 41.68 |
| quiet | OneSource | upper | 0.09259 | 15.34 | 0.006037 | 1 | 0.09259 | 42.08 | 301.96 | FairBind | 40.53 | 45.29 |
| quiet | OneSource | facilitator | 0.09259 | 15.34 | 0.006037 | 4 | 0.09311 | 66.68 | 277.03 | FairBind | 63.96 | 66.61 |
| quiet | CoinMarketCap | lower | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 132.08 | 36.57 | FI | 132.08 | 36.57 |
| quiet | CoinMarketCap | upper | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 132.37 | 37.86 | FI | 132.37 | 37.86 |
| quiet | CoinMarketCap | facilitator | 0.01557 | 1.557 | 0.01 | 1 | 0.01557 | 149.49 | 53.98 | FI | 149.49 | 53.98 |
| quiet | StableApify | lower | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 131.19 | 38.32 | FI | 131.19 | 38.32 |
| quiet | StableApify | upper | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 132.26 | 39.72 | FI | 132.26 | 39.72 |
| quiet | StableApify | facilitator | 0.016 | 1.733 | 0.009231 | 1 | 0.016 | 149.76 | 56.89 | FI | 149.76 | 56.89 |
| quiet | Exa(0.001 or less) | lower | 0.001 | 1 | 0.001 | 32 | 0.002618 | 1867.57 | 316.98 | FI | 1867.57 | 316.98 |
| quiet | Exa(0.001 or less) | upper | 0.001 | 1 | 0.001 | 1 | 0.001 | 1980.93 | 441.83 | FI | 1980.93 | 441.83 |
| quiet | Exa(0.001 or less) | facilitator | 0.001 | 1 | 0.001 | 32 | 0.002618 | 2056.36 | 505.77 | FI | 2056.36 | 505.77 |
| quiet | CoinStats(0.01 or less) | lower | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 664.83 | 297.18 | FI | 664.83 | 297.18 |
| quiet | CoinStats(0.01 or less) | upper | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 687.62 | 310.10 | FI | 687.62 | 310.10 |
| quiet | CoinStats(0.01 or less) | facilitator | 0.003667 | 3.667 | 0.001 | 1 | 0.003667 | 823.80 | 456.15 | FI | 823.80 | 456.15 |
| quiet | BlockRun | lower | 2.268 | 22.95 | 0.0988 | 32 | 41.72 | 3.90 | 1.63 | FI | 4.05 | 2.70 |
| quiet | BlockRun | upper | 2.268 | 22.95 | 0.0988 | 1 | 2.268 | 4.01 | 1.83 | FI | 4.15 | 2.89 |
| quiet | BlockRun | facilitator | 2.268 | 22.95 | 0.0988 | 32 | 41.72 | 5.42 | 3.14 | FI | 5.57 | 4.21 |

closed form seller own input applied values all in cells P9 and equal(upper reproduction). stylised curve(same R_e, v̄, activity ratio d, per epoch same sales count) value P9 and 0.05%p within cell 34 / 63. difference per epoch sales count not chosen not(anchor unit, release branch) and k11b E_k from the rule comes.


## 3. before payee region (tier 1a proof, per epoch sales count epochs, n_s values)

aggregate quiet window s1b(CDP) data 9/22 one day form, so(F/data-review/target_sellers_all_README.md 5 (line)) k11b quiet window(s1c) and differs. for reference only shown. busy window and median window name with seller n and R k11b and equal(`agg_match`).

(a) FairBind cheaper or equal and 10% or less, (b) FI cheaper and 10% or less, (c) two c 10% over(in parentheses: its among FairBind cheaper count / FI cheaper count).

| case | set | window | payee | revenue | (a) count | (a) revenue share | (b) count | (b) revenue share | (c) count | (c) revenue share |
|---|---|---|---|---|---|---|---|---|---|---|
| lower | Base(0x) payee | busy | 3392 | 235289.16 | 60 | 27.50 | 704 | 14.87 | 2628 (20 / 2608) | 57.63 |
| lower | Base(0x) payee | median | 18687 | 484196.10 | 76 | 20.08 | 988 | 71.13 | 17623 (15 / 17608) | 8.79 |
| lower | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 41 | 72.16 | 99 | 5.27 | 386 (13 / 373) | 22.57 |
| lower | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 4 | 1.16 | 537 | 16.86 | 2628 (20 / 2608) | 81.98 |
| lower | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 9 | 0.25 | 749 | 82.80 | 17623 (15 / 17608) | 16.94 |
| lower | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 4 | 0.54 | 74 | 14.47 | 386 (13 / 373) | 84.99 |
| lower | all payee(0x not address included) | busy | 5651 | 393066.34 | 95 | 21.20 | 2780 | 43.97 | 2776 (26 / 2750) | 34.83 |
| lower | all payee(0x not address included) | median | 20466 | 582603.80 | 89 | 31.36 | 2407 | 60.97 | 17970 (23 / 17947) | 7.66 |
| lower | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 51 | 76.87 | 256 | 14.83 | 589 (22 / 567) | 8.30 |
| upper | Base(0x) payee | busy | 3392 | 235289.16 | 60 | 27.49 | 701 | 14.87 | 2631 (22 / 2609) | 57.64 |
| upper | Base(0x) payee | median | 18687 | 484196.10 | 78 | 20.18 | 982 | 71.02 | 17627 (19 / 17608) | 8.79 |
| upper | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 42 | 72.19 | 95 | 5.23 | 389 (15 / 374) | 22.58 |
| upper | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 5 | 1.16 | 533 | 16.85 | 2631 (22 / 2609) | 82.00 |
| upper | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 11 | 0.45 | 743 | 82.59 | 17627 (19 / 17608) | 16.96 |
| upper | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 5 | 0.67 | 70 | 14.32 | 389 (15 / 374) | 85.01 |
| upper | all payee(0x not address included) | busy | 5651 | 393066.34 | 95 | 21.20 | 2777 | 43.97 | 2779 (28 / 2751) | 34.83 |
| upper | all payee(0x not address included) | median | 20466 | 582603.80 | 91 | 31.45 | 2401 | 60.89 | 17974 (27 / 17947) | 7.67 |
| upper | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 51 | 76.77 | 251 | 14.91 | 594 (24 / 570) | 8.32 |
| facilitator | Base(0x) payee | busy | 3392 | 235289.16 | 58 | 26.87 | 521 | 14.71 | 2813 (22 / 2791) | 58.42 |
| facilitator | Base(0x) payee | median | 18687 | 484196.10 | 73 | 20.00 | 850 | 44.41 | 17764 (18 / 17746) | 35.59 |
| facilitator | Base(0x) payee | quiet(reference only) | 526 | 89229.53 | 39 | 72.02 | 78 | 5.26 | 409 (15 / 394) | 22.72 |
| facilitator | Base(0x) payee, mean sales amount V or less | busy | 3169 | 165408.87 | 2 | 0.26 | 354 | 16.63 | 2813 (22 / 2791) | 83.11 |
| facilitator | Base(0x) payee, mean sales amount V or less | median | 18381 | 251120.85 | 6 | 0.09 | 611 | 31.29 | 17764 (18 / 17746) | 68.61 |
| facilitator | Base(0x) payee, mean sales amount V or less | quiet(reference only) | 464 | 23700.42 | 2 | 0.04 | 53 | 14.42 | 409 (15 / 394) | 85.54 |
| facilitator | all payee(0x not address included) | busy | 5651 | 393066.34 | 92 | 20.79 | 1799 | 43.80 | 3760 (29 / 3731) | 35.41 |
| facilitator | all payee(0x not address included) | median | 20466 | 582603.80 | 84 | 30.73 | 1679 | 38.61 | 18703 (28 / 18675) | 30.66 |
| facilitator | all payee(0x not address included) | quiet(reference only) | 896 | 252516.55 | 48 | 76.74 | 221 | 14.78 | 627 (25 / 602) | 8.48 |

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
