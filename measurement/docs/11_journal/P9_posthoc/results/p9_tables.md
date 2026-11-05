**all values post hoc calculations registered verdict none.** `p9.py` output. mode N, σ 1, r 10%, a 0, w 0.00173, per seller optimal k. costs revenue relative to %, *  10% over.

k11b_output.md reproduction: True. V0 Table 4 cell: True. measured path model constants put in V1 Table 4 cell: True. V0 FI(P3), FR(K14) max difference 1.1e-16, 0.0e+00. REL_M 16,800 vs P4 reference B and P3 (b) max difference 1.1e-16(k mismatch 0). additivity check max relative difference 0.0e+00(cell 756, anchor unit changed seller 42).

## 1. changed constant

| constant | k11b.py lines | model value | measured value | using variant |
|---|---|---|---|---|
| CL_REQ | 702 (new_values; 215 is the K11 value 96,000) | 119,160 | 151,629 | V1, V2 |
| CL_BILL | 206-214 | 157,644 | 170,701 | V1, V2 |
| release, seller epoch 256 items or less | 184~185, 539, 609 | fixed 114,624, per sale 2,930, closed per case 2,083 | fixed 75,331, per sale 16,920, closed per case -876 | V1, V3 |
| release, 256 items over | equal(capacity if over per transaction fixed) | equal | per unit 131,188, cursor 69,391, per sale 22,853 | V1, V3 |
| anchor unit(signature leaf) | 697~699(new_values), 191 | fixed 189,907, per leaf 21,649, per transaction leaf 924 | fixed 260,025, per leaf 28,126, per unit leaf 256 | V1, V4 |
| completion unit and first pull | none | none | fixed 299,810, per record 5,135 | V1, V4 |

V1 and V2 lower and facilitator case sample values also ECVRF Chainlink VRF v2.5 changes. V1t1 CL_BILL 165,162. measured for anchors EIP-7623 lower bound not set not(calc-rules.md 7.3).

## 2. set value (window: busy / median / quiet)

| set | V | case | V0 model(K11b, Table 4) | V1 all measured(VRF, release, anchor) | V2 VRF only | V3 release only | V4 anchor only | V1, claim gas attempt 1 times(sensitivity) |
|---|---|---|---|---|---|---|---|---|
| six seller sum | 1 | lower | 4.84 / 5.97 / 5.84 (10% within 3/3) | 9.19 / 11.67* / 11.89* (10% within 1/3) | 6.53 / 8.11 / 7.76 (10% within 3/3) | 6.12 / 7.69 / 8.06 (10% within 3/3) | 6.22 / 7.81 / 7.74 (10% within 3/3) | 9.14 / 11.60* / 11.83* (10% within 1/3) |
| six seller sum | 1 | upper | 6.84 / 8.51 / 8.10 (10% within 3/3) | 9.42 / 11.97* / 12.26* (10% within 1/3) | 7.14 / 8.90 / 8.44 (10% within 3/3) | 7.75 / 9.75 / 10.01* (10% within 2/3) | 8.21 / 10.35* / 10.00* (10% within 1/3) | 9.37 / 11.90* / 12.20* (10% within 1/3) |
| six seller sum | 1 | facilitator | 9.79 / 12.72* / 12.88* (10% within 1/3) | 14.13* / 18.42* / 18.93* (10% within 0/3) | 11.48* / 14.86* / 14.80* (10% within 0/3) | 11.07* / 14.44* / 15.11* (10% within 0/3) | 11.16* / 14.56* / 14.79* (10% within 0/3) | 14.08* / 18.35* / 18.87* (10% within 0/3) |
| six seller sum | 0.2 | lower | 8.05 / 8.59 / 8.39 (10% within 3/3) | 12.36* / 14.27* / 14.41* (10% within 0/3) | 9.74 / 10.73* / 10.31* (10% within 1/3) | 9.30 / 10.28* / 10.59* (10% within 1/3) | 9.42 / 10.43* / 10.29* (10% within 1/3) | 12.31* / 14.20* / 14.35* (10% within 0/3) |
| six seller sum | 0.2 | upper | 10.20* / 11.34* / 10.85* (10% within 0/3) | 12.74* / 14.75* / 14.97* (10% within 0/3) | 10.50* / 11.72* / 11.20* (10% within 0/3) | 11.09* / 12.54* / 12.74* (10% within 0/3) | 11.55* / 13.16* / 12.74* (10% within 0/3) | 12.69* / 14.68* / 14.91* (10% within 0/3) |
| six seller sum | 0.2 | facilitator | 12.99* / 15.35* / 15.43* (10% within 0/3) | 17.31* / 21.02* / 21.45* (10% within 0/3) | 14.68* / 17.49* / 17.35* (10% within 0/3) | 14.24* / 17.04* / 17.63* (10% within 0/3) | 14.36* / 17.19* / 17.34* (10% within 0/3) | 17.26* / 20.95* / 21.40* (10% within 0/3) |
| BlockRun | 1 | lower | 42.05* / 33.60* / 2.70 (10% within 1/3) | 48.25* / 35.42* / 3.90 (10% within 1/3) | 42.07* / 33.62* / 3.02 (10% within 1/3) | 46.53* / 34.87* / 3.19 (10% within 1/3) | 43.74* / 34.13* / 3.09 (10% within 1/3) | 48.25* / 35.42* / 3.89 (10% within 1/3) |
| BlockRun | 1 | upper | 42.10* / 33.64* / 3.10 (10% within 1/3) | 48.29* / 35.44* / 4.01 (10% within 1/3) | 42.10* / 33.64* / 3.16 (10% within 1/3) | 46.59* / 34.91* / 3.56 (10% within 1/3) | 43.79* / 34.17* / 3.49 (10% within 1/3) | 48.29* / 35.44* / 4.00 (10% within 1/3) |
| BlockRun | 1 | facilitator | 55.60* / 37.44* / 4.21 (10% within 1/3) | 61.80* / 39.25* / 5.42 (10% within 1/3) | 55.62* / 37.45* / 4.53 (10% within 1/3) | 60.08* / 38.70* / 4.71 (10% within 1/3) | 57.29* / 37.97* / 4.61 (10% within 1/3) | 61.80* / 39.25* / 5.41 (10% within 1/3) |
| BlockRun | 0.2 | lower | 95.13* / 78.11* / 4.71 (10% within 1/3) | 101.31* / 79.91* / 5.91 (10% within 1/3) | 95.15* / 78.13* / 5.03 (10% within 1/3) | 99.59* / 79.37* / 5.20 (10% within 1/3) | 96.83* / 78.64* / 5.10 (10% within 1/3) | 101.31* / 79.91* / 5.90 (10% within 1/3) |
| BlockRun | 0.2 | upper | 95.32* / 78.22* / 5.15 (10% within 1/3) | 101.46* / 80.00* / 6.04 (10% within 1/3) | 95.33* / 78.22* / 5.21 (10% within 1/3) | 99.78* / 79.48* / 5.60 (10% within 1/3) | 97.00* / 78.74* / 5.54 (10% within 1/3) | 101.46* / 80.00* / 6.03 (10% within 1/3) |
| BlockRun | 0.2 | facilitator | 108.68* / 81.95* / 6.23 (10% within 1/3) | 114.86* / 83.75* / 7.42 (10% within 1/3) | 108.70* / 81.96* / 6.54 (10% within 1/3) | 113.14* / 83.20* / 6.71 (10% within 1/3) | 110.38* / 82.48* / 6.62 (10% within 1/3) | 114.86* / 83.75* / 7.41 (10% within 1/3) |

## 3. per seller total (revenue relative to %, in parentheses chosen k; columns V0 model(K11b, Table 4), V1 all measured(VRF, release, anchor), V2 VRF only, V3 release only, V4 anchor only)


### six seller sum, V 1

| window | seller | case | V0 | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | 3.67 (32) | 6.74 (4) | 4.68 (32) | 4.73 (4) | 4.67 (32) |
| busy | OneSource | lower | 22.67* (32) | 45.46* (1) | 28.57* (32) | 31.42* (1) | 30.80* (32) |
| busy | CoinMarketCap | lower | 25.69* (32) | 54.29* (32) | 43.27* (32) | 29.10* (32) | 33.30* (32) |
| busy | StableApify | lower | 19.66* (1) | 35.63* (1) | 30.18* (1) | 20.43* (1) | 24.34* (1) |
| busy | Exa(0.001 or less) | lower | 806.14* (32) | 1586.67* (32) | 1400.39* (32) | 801.59* (32) | 996.99* (32) |
| busy | CoinStats(0.01 or less) | lower | 301.21* (1) | 541.47* (1) | 474.82* (1) | 301.24* (1) | 367.83* (1) |
| busy | StableEnrich(Out candidates excluded) | upper | 4.89 (1) | 6.85 (1) | 5.07 (1) | 5.68 (1) | 5.89 (1) |
| busy | OneSource | upper | 29.27* (1) | 45.79* (1) | 30.32* (1) | 36.60* (1) | 37.40* (1) |
| busy | CoinMarketCap | upper | 46.32* (1) | 58.11* (1) | 49.47* (1) | 47.36* (1) | 53.93* (1) |
| busy | StableApify | upper | 28.42* (1) | 35.75* (1) | 30.30* (1) | 29.19* (1) | 33.09* (1) |
| busy | Exa(0.001 or less) | upper | 1412.38* (1) | 1664.84* (1) | 1518.71* (1) | 1367.67* (1) | 1603.22* (1) |
| busy | CoinStats(0.01 or less) | upper | 447.59* (1) | 545.29* (1) | 478.65* (1) | 447.61* (1) | 514.20* (1) |
| busy | StableEnrich(Out candidates excluded) | facilitator | 7.62 (32) | 10.68* (4) | 8.62 (32) | 8.68 (4) | 8.62 (32) |
| busy | OneSource | facilitator | 57.41* (32) | 80.20* (1) | 63.31* (32) | 66.16* (1) | 65.54* (32) |
| busy | CoinMarketCap | facilitator | 41.47* (32) | 70.08* (32) | 59.06* (32) | 44.88* (32) | 49.08* (32) |
| busy | StableApify | facilitator | 29.79* (1) | 45.76* (1) | 40.31* (1) | 30.56* (1) | 34.47* (1) |
| busy | Exa(0.001 or less) | facilitator | 987.96* (32) | 1768.49* (32) | 1582.20* (32) | 983.40* (32) | 1178.80* (32) |
| busy | CoinStats(0.01 or less) | facilitator | 411.92* (1) | 652.17* (1) | 585.53* (1) | 411.94* (1) | 478.54* (1) |
| median | StableEnrich(Out candidates excluded) | lower | 4.00 (32) | 7.58 (8) | 5.38 (32) | 5.06 (8) | 5.15 (32) |
| median | OneSource | lower | 29.57* (32) | 61.29* (4) | 39.71* (32) | 40.52* (4) | 40.22* (32) |
| median | CoinMarketCap | lower | 43.61* (1) | 78.87* (1) | 69.10* (1) | 43.61* (1) | 53.39* (1) |
| median | StableApify | lower | 51.28* (1) | 91.93* (1) | 82.21* (1) | 50.10* (1) | 62.17* (1) |
| median | Exa(0.001 or less) | lower | 788.07* (32) | 1584.42* (32) | 1378.15* (32) | 804.64* (32) | 977.77* (32) |
| median | CoinStats(0.01 or less) | lower | 488.07* (1) | 870.96* (1) | 769.41* (1) | 484.59* (1) | 593.10* (1) |
| median | StableEnrich(Out candidates excluded) | upper | 5.67 (1) | 7.81 (1) | 5.91 (1) | 6.42 (1) | 6.81 (1) |
| median | OneSource | upper | 41.79* (1) | 62.37* (1) | 43.60* (1) | 49.92* (1) | 52.43* (1) |
| median | CoinMarketCap | upper | 64.72* (1) | 79.05* (1) | 69.28* (1) | 64.72* (1) | 74.50* (1) |
| median | StableApify | upper | 77.11* (1) | 92.36* (1) | 82.65* (1) | 75.93* (1) | 88.00* (1) |
| median | Exa(0.001 or less) | upper | 1402.50* (1) | 1653.62* (1) | 1508.09* (1) | 1358.34* (1) | 1592.20* (1) |
| median | CoinStats(0.01 or less) | upper | 728.04* (1) | 879.93* (1) | 778.38* (1) | 724.56* (1) | 833.07* (1) |
| median | StableEnrich(Out candidates excluded) | facilitator | 8.15 (32) | 11.73* (8) | 9.53 (32) | 9.21 (8) | 9.30 (32) |
| median | OneSource | facilitator | 71.84* (32) | 103.56* (4) | 81.97* (32) | 82.78* (4) | 82.48* (32) |
| median | CoinMarketCap | facilitator | 59.85* (1) | 95.11* (1) | 85.33* (1) | 59.85* (1) | 69.63* (1) |
| median | StableApify | facilitator | 65.82* (1) | 106.47* (1) | 96.75* (1) | 64.64* (1) | 76.71* (1) |
| median | Exa(0.001 or less) | facilitator | 969.65* (32) | 1765.99* (32) | 1559.72* (32) | 986.22* (32) | 1159.34* (32) |
| median | CoinStats(0.01 or less) | facilitator | 651.97* (1) | 1034.86* (1) | 933.31* (1) | 648.49* (1) | 757.00* (1) |
| quiet | StableEnrich(Out candidates excluded) | lower | 4.51 (32) | 9.16 (32) | 5.77 (32) | 6.40 (32) | 6.00 (32) |
| quiet | OneSource | lower | 20.15* (32) | 41.75* (4) | 27.88* (32) | 27.28* (4) | 26.89* (32) |
| quiet | CoinMarketCap | lower | 73.40* (1) | 132.08* (1) | 119.38* (1) | 70.69* (1) | 88.80* (1) |
| quiet | StableApify | lower | 73.40* (1) | 131.19* (1) | 118.16* (1) | 71.13* (1) | 88.69* (1) |
| quiet | Exa(0.001 or less) | lower | 929.62* (32) | 1867.57* (32) | 1645.76* (32) | 927.16* (32) | 1153.89* (32) |
| quiet | CoinStats(0.01 or less) | lower | 380.22* (1) | 664.83* (1) | 575.53* (1) | 388.07* (1) | 461.66* (1) |
| quiet | StableEnrich(Out candidates excluded) | upper | 6.04 (1) | 9.50 (1) | 6.26 (1) | 7.79 (1) | 7.52 (1) |
| quiet | OneSource | upper | 29.42* (1) | 42.08* (1) | 30.81* (1) | 33.96* (1) | 36.16* (1) |
| quiet | CoinMarketCap | upper | 111.45* (1) | 132.37* (1) | 119.68* (1) | 108.75* (1) | 126.85* (1) |
| quiet | StableApify | upper | 111.23* (1) | 132.26* (1) | 119.24* (1) | 108.96* (1) | 126.52* (1) |
| quiet | Exa(0.001 or less) | upper | 1689.30* (1) | 1980.93* (1) | 1817.44* (1) | 1628.53* (1) | 1913.56* (1) |
| quiet | CoinStats(0.01 or less) | upper | 563.38* (1) | 687.62* (1) | 598.33* (1) | 571.24* (1) | 644.82* (1) |
| quiet | StableEnrich(Out candidates excluded) | facilitator | 10.25* (32) | 14.90* (32) | 11.52* (32) | 12.14* (32) | 11.74* (32) |
| quiet | OneSource | facilitator | 45.08* (32) | 66.68* (4) | 52.81* (32) | 52.20* (4) | 51.82* (32) |
| quiet | CoinMarketCap | facilitator | 90.81* (1) | 149.49* (1) | 136.80* (1) | 88.11* (1) | 106.21* (1) |
| quiet | StableApify | facilitator | 91.97* (1) | 149.76* (1) | 136.73* (1) | 89.71* (1) | 107.27* (1) |
| quiet | Exa(0.001 or less) | facilitator | 1118.41* (32) | 2056.36* (32) | 1834.55* (32) | 1115.95* (32) | 1342.68* (32) |
| quiet | CoinStats(0.01 or less) | facilitator | 539.19* (1) | 823.80* (1) | 734.50* (1) | 547.05* (1) | 620.64* (1) |

### six seller sum, V 0.2

| window | seller | case | V0 | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | lower | 6.89 (32) | 9.93 (4) | 7.89 (32) | 7.92 (4) | 7.89 (32) |
| busy | OneSource | lower | 28.61* (32) | 51.37* (1) | 34.51* (32) | 37.33* (1) | 36.74* (32) |
| busy | CoinMarketCap | lower | 26.61* (32) | 55.18* (32) | 44.19* (32) | 29.99* (32) | 34.22* (32) |
| busy | StableApify | lower | 20.37* (1) | 36.31* (1) | 30.89* (1) | 21.11* (1) | 25.05* (1) |
| busy | Exa(0.001 or less) | lower | 805.04* (32) | 1585.54* (32) | 1399.29* (32) | 800.46* (32) | 995.88* (32) |
| busy | CoinStats(0.01 or less) | lower | 295.09* (1) | 535.32* (1) | 468.70* (1) | 295.09* (1) | 361.71* (1) |
| busy | StableEnrich(Out candidates excluded) | upper | 8.25 (1) | 10.16* (1) | 8.43 (1) | 9.00 (1) | 9.23 (1) |
| busy | OneSource | upper | 36.50* (1) | 52.97* (1) | 37.55* (1) | 43.80* (1) | 44.61* (1) |
| busy | CoinMarketCap | upper | 47.38* (1) | 59.12* (1) | 50.53* (1) | 48.39* (1) | 54.97* (1) |
| busy | StableApify | upper | 29.26* (1) | 36.55* (1) | 31.14* (1) | 30.01* (1) | 33.92* (1) |
| busy | Exa(0.001 or less) | upper | 1411.42* (1) | 1663.83* (1) | 1517.75* (1) | 1366.68* (1) | 1602.24* (1) |
| busy | CoinStats(0.01 or less) | upper | 441.61* (1) | 539.27* (1) | 472.67* (1) | 441.60* (1) | 508.20* (1) |
| busy | StableEnrich(Out candidates excluded) | facilitator | 10.83* (32) | 13.87* (4) | 11.84* (32) | 11.87* (4) | 11.84* (32) |
| busy | OneSource | facilitator | 63.35* (32) | 86.11* (1) | 69.25* (32) | 72.07* (1) | 71.48* (32) |
| busy | CoinMarketCap | facilitator | 42.39* (32) | 70.97* (32) | 59.98* (32) | 45.78* (32) | 50.00* (32) |
| busy | StableApify | facilitator | 30.49* (1) | 46.44* (1) | 41.01* (1) | 31.24* (1) | 35.18* (1) |
| busy | Exa(0.001 or less) | facilitator | 986.86* (32) | 1767.36* (32) | 1581.10* (32) | 982.27* (32) | 1177.70* (32) |
| busy | CoinStats(0.01 or less) | facilitator | 405.80* (1) | 646.03* (1) | 579.41* (1) | 405.80* (1) | 472.42* (1) |
| median | StableEnrich(Out candidates excluded) | lower | 6.39 (32) | 9.94 (8) | 7.76 (32) | 7.42 (8) | 7.54 (32) |
| median | OneSource | lower | 35.61* (32) | 67.30* (4) | 45.74* (32) | 46.53* (4) | 46.25* (32) |
| median | CoinMarketCap | lower | 44.19* (1) | 79.42* (1) | 69.67* (1) | 44.16* (1) | 53.97* (1) |
| median | StableApify | lower | 51.40* (1) | 92.02* (1) | 82.33* (1) | 50.19* (1) | 62.29* (1) |
| median | Exa(0.001 or less) | lower | 787.20* (32) | 1583.52* (32) | 1377.28* (32) | 803.74* (32) | 976.90* (32) |
| median | CoinStats(0.01 or less) | lower | 472.48* (1) | 855.35* (1) | 753.82* (1) | 468.97* (1) | 577.52* (1) |
| median | StableEnrich(Out candidates excluded) | upper | 8.17 (1) | 10.27* (1) | 8.42 (1) | 8.90 (1) | 9.30 (1) |
| median | OneSource | upper | 49.11* (1) | 69.65* (1) | 50.93* (1) | 57.22* (1) | 59.73* (1) |
| median | CoinMarketCap | upper | 65.44* (1) | 79.72* (1) | 70.00* (1) | 65.41* (1) | 75.19* (1) |
| median | StableApify | upper | 77.37* (1) | 92.57* (1) | 82.91* (1) | 76.16* (1) | 88.24* (1) |
| median | Exa(0.001 or less) | upper | 1401.78* (1) | 1652.85* (1) | 1507.36* (1) | 1357.59* (1) | 1591.45* (1) |
| median | CoinStats(0.01 or less) | upper | 712.60* (1) | 864.44* (1) | 762.94* (1) | 709.09* (1) | 817.61* (1) |
| median | StableEnrich(Out candidates excluded) | facilitator | 10.54* (32) | 14.09* (8) | 11.91* (32) | 11.57* (8) | 11.68* (32) |
| median | OneSource | facilitator | 77.88* (32) | 109.56* (4) | 88.01* (32) | 88.79* (4) | 88.52* (32) |
| median | CoinMarketCap | facilitator | 60.43* (1) | 95.65* (1) | 85.91* (1) | 60.39* (1) | 70.20* (1) |
| median | StableApify | facilitator | 65.94* (1) | 106.56* (1) | 96.87* (1) | 64.73* (1) | 76.83* (1) |
| median | Exa(0.001 or less) | facilitator | 968.78* (32) | 1765.10* (32) | 1558.86* (32) | 985.32* (32) | 1158.48* (32) |
| median | CoinStats(0.01 or less) | facilitator | 636.38* (1) | 1019.25* (1) | 917.72* (1) | 632.87* (1) | 741.42* (1) |
| quiet | StableEnrich(Out candidates excluded) | lower | 6.82 (32) | 11.45* (32) | 8.09 (32) | 8.69 (32) | 8.31 (32) |
| quiet | OneSource | lower | 26.17* (32) | 47.74* (4) | 33.90* (32) | 33.26* (4) | 32.91* (32) |
| quiet | CoinMarketCap | lower | 73.91* (1) | 132.56* (1) | 119.90* (1) | 71.18* (1) | 89.31* (1) |
| quiet | StableApify | lower | 72.89* (1) | 130.65* (1) | 117.65* (1) | 70.59* (1) | 88.18* (1) |
| quiet | Exa(0.001 or less) | lower | 928.63* (32) | 1866.55* (32) | 1644.77* (32) | 926.14* (32) | 1152.90* (32) |
| quiet | CoinStats(0.01 or less) | lower | 351.19* (1) | 635.77* (1) | 546.50* (1) | 359.01* (1) | 432.63* (1) |
| quiet | StableEnrich(Out candidates excluded) | upper | 8.48 (1) | 11.90* (1) | 8.70 (1) | 10.20* (1) | 9.95 (1) |
| quiet | OneSource | upper | 36.73* (1) | 49.34* (1) | 38.11* (1) | 41.24* (1) | 43.45* (1) |
| quiet | CoinMarketCap | upper | 112.10* (1) | 132.97* (1) | 120.33* (1) | 109.37* (1) | 127.48* (1) |
| quiet | StableApify | upper | 110.85* (1) | 131.84* (1) | 118.86* (1) | 108.56* (1) | 126.13* (1) |
| quiet | Exa(0.001 or less) | upper | 1688.45* (1) | 1980.03* (1) | 1816.59* (1) | 1627.65* (1) | 1912.69* (1) |
| quiet | CoinStats(0.01 or less) | upper | 534.49* (1) | 658.68* (1) | 569.44* (1) | 542.31* (1) | 615.91* (1) |
| quiet | StableEnrich(Out candidates excluded) | facilitator | 12.57* (32) | 17.19* (32) | 13.83* (32) | 14.43* (32) | 14.06* (32) |
| quiet | OneSource | facilitator | 51.09* (32) | 72.66* (4) | 58.83* (32) | 58.19* (4) | 57.83* (32) |
| quiet | CoinMarketCap | facilitator | 91.32* (1) | 149.97* (1) | 137.31* (1) | 88.59* (1) | 106.72* (1) |
| quiet | StableApify | facilitator | 91.46* (1) | 149.22* (1) | 136.22* (1) | 89.17* (1) | 106.75* (1) |
| quiet | Exa(0.001 or less) | facilitator | 1117.42* (32) | 2055.34* (32) | 1833.56* (32) | 1114.93* (32) | 1341.69* (32) |
| quiet | CoinStats(0.01 or less) | facilitator | 510.16* (1) | 794.74* (1) | 705.47* (1) | 517.99* (1) | 591.61* (1) |

### BlockRun, V 1

| window | seller | case | V0 | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|---|---|
| busy | BlockRun | lower | 42.05* (4) | 48.25* (8) | 42.07* (4) | 46.53* (8) | 43.74* (4) |
| busy | BlockRun | upper | 42.10* (1) | 48.29* (1) | 42.10* (1) | 46.59* (1) | 43.79* (1) |
| busy | BlockRun | facilitator | 55.60* (4) | 61.80* (8) | 55.62* (4) | 60.08* (8) | 57.29* (4) |
| median | BlockRun | lower | 33.60* (4) | 35.42* (8) | 33.62* (4) | 34.87* (8) | 34.13* (4) |
| median | BlockRun | upper | 33.64* (1) | 35.44* (1) | 33.64* (1) | 34.91* (1) | 34.17* (1) |
| median | BlockRun | facilitator | 37.44* (4) | 39.25* (8) | 37.45* (4) | 38.70* (8) | 37.97* (4) |
| quiet | BlockRun | lower | 2.70 (32) | 3.90 (32) | 3.02 (32) | 3.19 (32) | 3.09 (32) |
| quiet | BlockRun | upper | 3.10 (1) | 4.01 (1) | 3.16 (1) | 3.56 (1) | 3.49 (1) |
| quiet | BlockRun | facilitator | 4.21 (32) | 5.42 (32) | 4.53 (32) | 4.71 (32) | 4.61 (32) |

### BlockRun, V 0.2

| window | seller | case | V0 | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|---|---|
| busy | BlockRun | lower | 95.13* (4) | 101.31* (8) | 95.15* (4) | 99.59* (8) | 96.83* (4) |
| busy | BlockRun | upper | 95.32* (1) | 101.46* (1) | 95.33* (1) | 99.78* (1) | 97.00* (1) |
| busy | BlockRun | facilitator | 108.68* (4) | 114.86* (8) | 108.70* (4) | 113.14* (8) | 110.38* (4) |
| median | BlockRun | lower | 78.11* (4) | 79.91* (8) | 78.13* (4) | 79.37* (8) | 78.64* (4) |
| median | BlockRun | upper | 78.22* (1) | 80.00* (1) | 78.22* (1) | 79.48* (1) | 78.74* (1) |
| median | BlockRun | facilitator | 81.95* (4) | 83.75* (8) | 81.96* (4) | 83.20* (8) | 82.48* (4) |
| quiet | BlockRun | lower | 4.71 (32) | 5.91 (32) | 5.03 (32) | 5.20 (32) | 5.10 (32) |
| quiet | BlockRun | upper | 5.15 (1) | 6.04 (1) | 5.21 (1) | 5.60 (1) | 5.54 (1) |
| quiet | BlockRun | facilitator | 6.23 (32) | 7.42 (32) | 6.54 (32) | 6.71 (32) | 6.62 (32) |

## 4. full inspection FI with comparison (V 1; FI V1 measured release, VRF and anchor none)

| set | window | case | V0 FB | V0 FI | V1 FB | V1 FB V 0.2 | V1 FI | V1 more cheaper side(sum) | V1 FI cheaper seller count | its revenue share | V1 per seller cheaper side mixed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| six seller sum | busy | lower | 4.84 | 13.42 | 9.19 | 12.36 | 14.47 | FairBind | 4/6 | 3.05 | 8.13 |
| six seller sum | busy | upper | 6.84 | 15.75 | 9.42 | 12.74 | 16.44 | FairBind | 4/6 | 3.05 | 8.41 |
| six seller sum | busy | facilitator | 9.79 | 18.36 | 14.13 | 17.31 | 19.41 | FairBind | 4/6 | 3.05 | 13.08 |
| six seller sum | median | lower | 5.97 | 33.90 | 11.67 | 14.27 | 35.31 | FairBind | 5/6 | 93.33 | 10.89 |
| six seller sum | median | upper | 8.51 | 40.63 | 11.97 | 14.75 | 41.55 | FairBind | 5/6 | 93.33 | 11.49 |
| six seller sum | median | facilitator | 12.72 | 40.66 | 18.42 | 21.02 | 42.06 | FairBind | 5/6 | 93.33 | 17.64 |
| six seller sum | quiet | lower | 5.84 | 24.16 | 11.89 | 14.41 | 26.06 | FairBind | 4/6 | 0.18 | 11.38 |
| six seller sum | quiet | upper | 8.10 | 28.48 | 12.26 | 14.97 | 30.06 | FairBind | 4/6 | 0.18 | 11.75 |
| six seller sum | quiet | facilitator | 12.88 | 31.20 | 18.93 | 21.45 | 33.10 | FairBind | 4/6 | 0.18 | 18.42 |
| BlockRun | busy | lower | 42.05 | 9.36 | 48.25 | 101.31 | 13.20 | FI | 1/1 | 100.00 | 13.20 |
| BlockRun | busy | upper | 42.10 | 10.55 | 48.29 | 101.46 | 14.39 | FI | 1/1 | 100.00 | 14.39 |
| BlockRun | busy | facilitator | 55.60 | 22.91 | 61.80 | 114.86 | 26.75 | FI | 1/1 | 100.00 | 26.75 |
| BlockRun | median | lower | 33.60 | 2.78 | 35.42 | 79.91 | 3.86 | FI | 1/1 | 100.00 | 3.86 |
| BlockRun | median | upper | 33.64 | 3.11 | 35.44 | 80.00 | 4.20 | FI | 1/1 | 100.00 | 4.20 |
| BlockRun | median | facilitator | 37.44 | 6.61 | 39.25 | 83.75 | 7.70 | FI | 1/1 | 100.00 | 7.70 |
| BlockRun | quiet | lower | 2.70 | 1.20 | 3.90 | 5.91 | 1.63 | FI | 1/1 | 100.00 | 1.63 |
| BlockRun | quiet | upper | 3.10 | 1.44 | 4.01 | 6.04 | 1.83 | FI | 1/1 | 100.00 | 1.83 |
| BlockRun | quiet | facilitator | 4.21 | 2.71 | 5.42 | 7.42 | 3.14 | FI | 1/1 | 100.00 | 3.14 |

per seller (V1, V 1; FB total / FI total, in parentheses chosen k):

| set | window | seller | lower | upper | facilitator |
|---|---|---|---|---|---|
| six seller sum | busy | StableEnrich(Out candidates excluded) | 6.74 (4) / 6.89 (4) | 6.85 (1) / 7.32 (1) | 10.68 (4) / 10.84 (4) |
| six seller sum | busy | OneSource | 45.46 (1) / 353.24 (1) | 45.79 (1) / 423.27 (1) | 80.20 (1) / 387.98 (1) |
| six seller sum | busy | CoinMarketCap | 54.29 (32) / 25.60 (32) FI cheaper | 58.11 (1) / 30.67 (1) FI cheaper | 70.08 (32) / 41.38 (32) FI cheaper |
| six seller sum | busy | StableApify | 35.63 (1) / 18.79 (1) FI cheaper | 35.75 (1) / 19.62 (1) FI cheaper | 45.76 (1) / 28.92 (1) FI cheaper |
| six seller sum | busy | Exa(0.001 or less) | 1586.67 (32) / 321.01 (32) FI cheaper | 1664.84 (1) / 411.00 (1) FI cheaper | 1768.49 (32) / 502.82 (32) FI cheaper |
| six seller sum | busy | CoinStats(0.01 or less) | 541.47 (1) / 212.90 (1) FI cheaper | 545.29 (1) / 221.71 (1) FI cheaper | 652.17 (1) / 323.61 (1) FI cheaper |
| six seller sum | median | StableEnrich(Out candidates excluded) | 7.58 (8) / 7.16 (8) FI cheaper | 7.81 (1) / 7.71 (1) FI cheaper | 11.73 (8) / 11.31 (8) FI cheaper |
| six seller sum | median | OneSource | 61.29 (4) / 427.62 (4) | 62.37 (1) / 513.23 (1) | 103.56 (4) / 469.88 (4) |
| six seller sum | median | CoinMarketCap | 78.87 (1) / 31.38 (1) FI cheaper | 79.05 (1) / 32.67 (1) FI cheaper | 95.11 (1) / 47.62 (1) FI cheaper |
| six seller sum | median | StableApify | 91.93 (1) / 29.39 (1) FI cheaper | 92.36 (1) / 30.51 (1) FI cheaper | 106.47 (1) / 43.93 (1) FI cheaper |
| six seller sum | median | Exa(0.001 or less) | 1584.42 (32) / 328.78 (32) FI cheaper | 1653.62 (1) / 409.94 (1) FI cheaper | 1765.99 (32) / 510.36 (32) FI cheaper |
| six seller sum | median | CoinStats(0.01 or less) | 870.96 (1) / 318.94 (1) FI cheaper | 879.93 (1) / 331.86 (1) FI cheaper | 1034.86 (1) / 482.83 (1) FI cheaper |
| six seller sum | quiet | StableEnrich(Out candidates excluded) | 9.16 (32) / 10.32 (32) | 9.50 (1) / 11.13 (1) | 14.90 (32) / 16.06 (32) |
| six seller sum | quiet | OneSource | 41.75 (4) / 252.11 (4) | 42.08 (1) / 301.96 (1) | 66.68 (4) / 277.03 (4) |
| six seller sum | quiet | CoinMarketCap | 132.08 (1) / 36.57 (1) FI cheaper | 132.37 (1) / 37.86 (1) FI cheaper | 149.49 (1) / 53.98 (1) FI cheaper |
| six seller sum | quiet | StableApify | 131.19 (1) / 38.32 (1) FI cheaper | 132.26 (1) / 39.72 (1) FI cheaper | 149.76 (1) / 56.89 (1) FI cheaper |
| six seller sum | quiet | Exa(0.001 or less) | 1867.57 (32) / 316.98 (32) FI cheaper | 1980.93 (1) / 441.83 (1) FI cheaper | 2056.36 (32) / 505.77 (32) FI cheaper |
| six seller sum | quiet | CoinStats(0.01 or less) | 664.83 (1) / 297.18 (1) FI cheaper | 687.62 (1) / 310.10 (1) FI cheaper | 823.80 (1) / 456.15 (1) FI cheaper |
| BlockRun | busy | BlockRun | 48.25 (8) / 13.20 (8) FI cheaper | 48.29 (1) / 14.39 (1) FI cheaper | 61.80 (8) / 26.75 (8) FI cheaper |
| BlockRun | median | BlockRun | 35.42 (8) / 3.86 (8) FI cheaper | 35.44 (1) / 4.20 (1) FI cheaper | 39.25 (8) / 7.70 (8) FI cheaper |
| BlockRun | quiet | BlockRun | 3.90 (32) / 1.63 (32) FI cheaper | 4.01 (1) / 1.83 (1) FI cheaper | 5.42 (32) / 3.14 (32) FI cheaper |

## 5. fixed sampling rate FR order (K14 definition, six seller sum, lower, V 1)

| variant | window | FB | FR main | FR-lo | FR main − FB (%p) | FR-lo − FB (%p) | FR main > FB | FR-lo > FB |
|---|---|---|---|---|---|---|---|---|
| V0 | busy | 4.84 | 12.22 | 8.73 | +7.38 | +3.89 | True | True |
| V0 | median | 5.97 | 12.74 | 10.02 | +6.77 | +4.05 | True | True |
| V0 | quiet | 5.84 | 16.29 | 11.28 | +10.45 | +5.44 | True | True |
| V1 | busy | 9.19 | 16.52 | 13.05 | +7.33 | +3.86 | True | True |
| V1 | median | 11.67 | 18.38 | 15.68 | +6.71 | +4.02 | True | True |
| V1 | quiet | 11.89 | 22.25 | 17.28 | +10.36 | +5.39 | True | True |
| V2 | busy | 6.53 | 13.91 | 10.42 | +7.38 | +3.89 | True | True |
| V2 | median | 8.11 | 14.88 | 12.16 | +6.77 | +4.05 | True | True |
| V2 | quiet | 7.76 | 18.21 | 13.20 | +10.45 | +5.44 | True | True |
| V3 | busy | 6.12 | 13.45 | 9.98 | +7.33 | +3.86 | True | True |
| V3 | median | 7.69 | 14.40 | 11.70 | +6.71 | +4.02 | True | True |
| V3 | quiet | 8.06 | 18.42 | 13.46 | +10.36 | +5.39 | True | True |
| V4 | busy | 6.22 | 13.60 | 10.11 | +7.38 | +3.89 | True | True |
| V4 | median | 7.81 | 14.58 | 11.86 | +6.77 | +4.05 | True | True |
| V4 | quiet | 7.74 | 18.19 | 13.18 | +10.45 | +5.44 | True | True |
