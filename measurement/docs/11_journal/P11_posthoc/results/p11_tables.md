**all values post hoc calculations registered verdict none.** `p11.py` output. mode N, σ 1, r 10%, a 0, per seller optimal k, costs revenue relative to %, *  10% over. reference variant V1u(real USDC constant), comparison V1(mock).

reproduction check: k11b True, V1 vs p9.json True(max difference 0.0e+00), V0 FI and FR True, P3 FI_min / FI_W / FI True, P3 g* True(max difference 2.3e-10 gas), StableEnrich g*_FI [49734, 52253, 41406], P10 check True, P10 threshold True, P6 True.

## 1. (c) V1u and V1: header numbers and FI comparison

| set | V | case | V1u (busy / median / quiet) | V1 (busy / median / quiet) | V1u − V1 (%p) |
|---|---|---|---|---|---|
| six seller sum | 1 | lower | 9.21 / 11.70* / 11.92* | 9.19 / 11.67* / 11.89* | +0.03 / +0.03 / +0.03 |
| six seller sum | 1 | upper | 9.50 / 12.06* / 12.34* | 9.42 / 11.97* / 12.26* | +0.07 / +0.09 / +0.09 |
| six seller sum | 1 | facilitator | 14.16* / 18.45* / 18.96* | 14.13* / 18.42* / 18.93* | +0.03 / +0.03 / +0.03 |
| six seller sum | 0.2 | lower | 12.39* / 14.30* / 14.44* | 12.36* / 14.27* / 14.41* | +0.03 / +0.03 / +0.03 |
| six seller sum | 0.2 | upper | 12.81* / 14.84* / 15.05* | 12.74* / 14.75* / 14.97* | +0.07 / +0.09 / +0.09 |
| six seller sum | 0.2 | facilitator | 17.33* / 21.05* / 21.49* | 17.31* / 21.02* / 21.45* | +0.03 / +0.03 / +0.03 |
| BlockRun | 1 | lower | 48.26* / 35.42* / 3.91 | 48.25* / 35.42* / 3.90 | +0.01 / +0.00 / +0.00 |
| BlockRun | 1 | upper | 48.30* / 35.45* / 4.02 | 48.29* / 35.44* / 4.01 | +0.01 / +0.00 / +0.01 |
| BlockRun | 1 | facilitator | 61.81* / 39.26* / 5.42 | 61.80* / 39.25* / 5.42 | +0.01 / +0.00 / +0.00 |
| BlockRun | 0.2 | lower | 101.32* / 79.92* / 5.91 | 101.31* / 79.91* / 5.91 | +0.01 / +0.00 / +0.00 |
| BlockRun | 0.2 | upper | 101.47* / 80.00* / 6.06 | 101.46* / 80.00* / 6.04 | +0.01 / +0.00 / +0.01 |
| BlockRun | 0.2 | facilitator | 114.87* / 83.75* / 7.42 | 114.86* / 83.75* / 7.42 | +0.01 / +0.00 / +0.00 |

FI comparison(V 1): FB sum / FI sum, more cheaper side, FI cheaper seller count, its revenue share, per seller cheaper side mixed.

| reference | set | window | case | FB | FI | more cheaper side | FI cheaper count | share | mixed |
|---|---|---|---|---|---|---|---|---|---|
| V1u | six seller sum | busy | lower | 9.21 | 14.50 | FairBind | 4/6 | 3.05 | 8.16 |
| V1u | six seller sum | busy | upper | 9.50 | 16.51 | FairBind | 4/6 | 3.05 | 8.48 |
| V1u | six seller sum | busy | facilitator | 14.16 | 19.44 | FairBind | 4/6 | 3.05 | 13.10 |
| V1u | six seller sum | median | lower | 11.70 | 35.34 | FairBind | 5/6 | 93.33 | 10.92 |
| V1u | six seller sum | median | upper | 12.06 | 41.64 | FairBind | 5/6 | 93.33 | 11.59 |
| V1u | six seller sum | median | facilitator | 18.45 | 42.09 | FairBind | 5/6 | 93.33 | 17.67 |
| V1u | six seller sum | quiet | lower | 11.92 | 26.09 | FairBind | 4/6 | 0.18 | 11.41 |
| V1u | six seller sum | quiet | upper | 12.34 | 30.15 | FairBind | 4/6 | 0.18 | 11.84 |
| V1u | six seller sum | quiet | facilitator | 18.96 | 33.13 | FairBind | 4/6 | 0.18 | 18.46 |
| V1u | BlockRun | busy | lower | 48.26 | 13.21 | FI | 1/1 | 100.00 | 13.21 |
| V1u | BlockRun | busy | upper | 48.30 | 14.40 | FI | 1/1 | 100.00 | 14.40 |
| V1u | BlockRun | busy | facilitator | 61.81 | 26.76 | FI | 1/1 | 100.00 | 26.76 |
| V1u | BlockRun | median | lower | 35.42 | 3.87 | FI | 1/1 | 100.00 | 3.87 |
| V1u | BlockRun | median | upper | 35.45 | 4.21 | FI | 1/1 | 100.00 | 4.21 |
| V1u | BlockRun | median | facilitator | 39.26 | 7.70 | FI | 1/1 | 100.00 | 7.70 |
| V1u | BlockRun | quiet | lower | 3.91 | 1.63 | FI | 1/1 | 100.00 | 1.63 |
| V1u | BlockRun | quiet | upper | 4.02 | 1.85 | FI | 1/1 | 100.00 | 1.85 |
| V1u | BlockRun | quiet | facilitator | 5.42 | 3.15 | FI | 1/1 | 100.00 | 3.15 |
| V1 | six seller sum | busy | lower | 9.19 | 14.47 | FairBind | 4/6 | 3.05 | 8.13 |
| V1 | six seller sum | busy | upper | 9.42 | 16.44 | FairBind | 4/6 | 3.05 | 8.41 |
| V1 | six seller sum | busy | facilitator | 14.13 | 19.41 | FairBind | 4/6 | 3.05 | 13.08 |
| V1 | six seller sum | median | lower | 11.67 | 35.31 | FairBind | 5/6 | 93.33 | 10.89 |
| V1 | six seller sum | median | upper | 11.97 | 41.55 | FairBind | 5/6 | 93.33 | 11.49 |
| V1 | six seller sum | median | facilitator | 18.42 | 42.06 | FairBind | 5/6 | 93.33 | 17.64 |
| V1 | six seller sum | quiet | lower | 11.89 | 26.06 | FairBind | 4/6 | 0.18 | 11.38 |
| V1 | six seller sum | quiet | upper | 12.26 | 30.06 | FairBind | 4/6 | 0.18 | 11.75 |
| V1 | six seller sum | quiet | facilitator | 18.93 | 33.10 | FairBind | 4/6 | 0.18 | 18.42 |
| V1 | BlockRun | busy | lower | 48.25 | 13.20 | FI | 1/1 | 100.00 | 13.20 |
| V1 | BlockRun | busy | upper | 48.29 | 14.39 | FI | 1/1 | 100.00 | 14.39 |
| V1 | BlockRun | busy | facilitator | 61.80 | 26.75 | FI | 1/1 | 100.00 | 26.75 |
| V1 | BlockRun | median | lower | 35.42 | 3.86 | FI | 1/1 | 100.00 | 3.86 |
| V1 | BlockRun | median | upper | 35.44 | 4.20 | FI | 1/1 | 100.00 | 4.20 |
| V1 | BlockRun | median | facilitator | 39.25 | 7.70 | FI | 1/1 | 100.00 | 7.70 |
| V1 | BlockRun | quiet | lower | 3.90 | 1.63 | FI | 1/1 | 100.00 | 1.63 |
| V1 | BlockRun | quiet | upper | 4.01 | 1.83 | FI | 1/1 | 100.00 | 1.83 |
| V1 | BlockRun | quiet | facilitator | 5.42 | 3.14 | FI | 1/1 | 100.00 | 3.14 |

## 2. (a) measured gas full inspection

FI point(g, tier 1a): same 86,824, own_lo 31,315, own_a 45,615, own_b 72,615, own_bind_a 54,311, own_bind_b 81,311. tier 0 same share without TEE as is.


### V1u: FI point, six seller sum (lower, V 1)

| point | window | FB sum | FI sum | mixed | (A) FB cheaper and ≤10%: seller, revenue share | (B) FI cheaper and ≤10%: seller, revenue share |
|---|---|---|---|---|---|---|
| pt|same | busy | 9.21 | 14.50 | 8.16 | StableEnrich(Out candidates excluded); 94.94 | none; 0.00 |
| pt|same | median | 11.70 | 35.34 | 10.92 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|same | quiet | 11.92 | 26.09 | 11.41 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |
| pt|own_lo | busy | 9.21 | 10.12 | 4.56 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_lo | median | 11.70 | 29.36 | 7.45 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_lo | quiet | 11.92 | 19.84 | 7.67 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_a | busy | 9.21 | 11.25 | 5.52 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_a | median | 11.70 | 30.90 | 8.34 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_a | quiet | 11.92 | 21.45 | 8.91 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_b | busy | 9.21 | 13.38 | 7.35 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_b | median | 11.70 | 33.81 | 10.03 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_b | quiet | 11.92 | 24.49 | 11.26 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_bind_a | busy | 9.21 | 11.94 | 6.11 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_bind_a | median | 11.70 | 31.84 | 8.89 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_bind_a | quiet | 11.92 | 22.43 | 9.67 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_bind_b | busy | 9.21 | 14.06 | 7.93 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_bind_b | median | 11.70 | 34.75 | 10.58 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_bind_b | quiet | 11.92 | 25.47 | 11.41 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |
| teeW | busy | 9.21 | 14.50 | 8.16 | StableEnrich(Out candidates excluded); 94.94 | none; 0.00 |
| teeW | median | 11.70 | 35.34 | 10.92 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| teeW | quiet | 11.92 | 26.09 | 11.41 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |

### V1u: g grid (lower, V 1; form fi: FairBind measured call)

| form | g | six (A) share / (B) share busy | six (A) share / (B) share median | six (A) share / (B) share quiet | BlockRun region | payee (A) count, share / (B) count, share |
|---|---|---|---|---|---|---|
| fi | 20,000 | 0.00 / 97.97 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 636, 82.50; median 0, 0.00 / 889, 83.45 |
| fi | 25,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 627, 18.78; median 0, 0.00 / 873, 83.42 |
| fi | 30,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 618, 18.59; median 0, 0.00 / 859, 83.26 |
| fi | 31,315 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 617, 18.57; median 0, 0.00 / 858, 83.26 |
| fi | 35,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 613, 18.57; median 0, 0.00 / 852, 83.26 |
| fi | 40,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 606, 18.56; median 0, 0.00 / 843, 83.24 |
| fi | 45,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 601, 18.56; median 0, 0.00 / 836, 83.23 |
| fi | 45,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 601, 18.56; median 0, 0.00 / 834, 83.22 |
| fi | 50,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 596, 18.54; median 0, 0.00 / 823, 83.22 |
| fi | 54,311 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 591, 18.49; median 0, 0.00 / 815, 83.22 |
| fi | 55,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 591, 18.49; median 0, 0.00 / 813, 83.22 |
| fi | 60,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 561, 18.24; median 1, 0.01 / 784, 83.18 |
| fi | 65,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 554, 18.01; median 1, 0.01 / 776, 83.15 |
| fi | 70,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 548, 17.92; median 3, 0.02 / 767, 83.05 |
| fi | 72,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 545, 17.92; median 5, 0.19 / 762, 82.87 |
| fi | 75,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 544, 17.92; median 5, 0.19 / 756, 82.87 |
| fi | 80,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 540, 17.76; median 7, 0.25 / 752, 82.81 |
| fi | 81,311 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 540, 17.76; median 7, 0.25 / 751, 82.81 |
| fi | 85,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 536, 16.86; median 8, 0.25 / 747, 82.81 |
| fi | 86,824 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 534, 16.86; median 9, 0.25 / 746, 82.80 |
| fi | 90,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 530, 16.85; median 11, 0.45 / 741, 82.61 |
| fi | 95,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 528, 16.84; median 12, 0.90 / 734, 82.14 |
| fi | 100,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 7, 1.55 / 522, 16.45; median 13, 0.91 / 727, 82.13 |
| fi | 105,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 9, 1.88 / 483, 16.11; median 14, 0.91 / 667, 82.12 |
| fi | 110,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 478, 16.09; median 15, 0.92 / 661, 82.11 |
| fi | 115,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 472, 16.05; median 16, 0.93 / 654, 82.08 |
| fi | 120,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 17, 2.24 / 463, 15.64; median 19, 1.11 / 645, 81.90 |
| both | 20,000 | 0.00 / 97.97 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 636, 82.50; median 0, 0.00 / 889, 83.45 |
| both | 25,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 627, 18.78; median 0, 0.00 / 873, 83.42 |
| both | 30,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 618, 18.59; median 0, 0.00 / 859, 83.26 |
| both | 31,315 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 617, 18.57; median 0, 0.00 / 858, 83.26 |
| both | 35,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 613, 18.57; median 0, 0.00 / 852, 83.26 |
| both | 40,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 606, 18.56; median 0, 0.00 / 843, 83.24 |
| both | 45,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 601, 18.56; median 0, 0.00 / 836, 83.23 |
| both | 45,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 601, 18.56; median 0, 0.00 / 834, 83.22 |
| both | 50,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 596, 18.54; median 0, 0.00 / 823, 83.22 |
| both | 54,311 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 590, 18.26; median 0, 0.00 / 815, 83.22 |
| both | 55,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 590, 18.26; median 1, 0.01 / 812, 83.21 |
| both | 60,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 561, 18.24; median 1, 0.01 / 784, 83.18 |
| both | 65,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 554, 18.01; median 1, 0.01 / 776, 83.15 |
| both | 70,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 548, 17.92; median 4, 0.05 / 766, 83.02 |
| both | 72,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 545, 17.92; median 5, 0.19 / 762, 82.87 |
| both | 75,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 544, 17.92; median 6, 0.25 / 755, 82.81 |
| both | 80,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 540, 17.76; median 7, 0.25 / 752, 82.81 |
| both | 81,311 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 540, 17.76; median 7, 0.25 / 751, 82.81 |
| both | 85,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 536, 16.86; median 8, 0.25 / 747, 82.81 |
| both | 86,824 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 534, 16.86; median 9, 0.25 / 746, 82.80 |
| both | 90,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 530, 16.85; median 11, 0.45 / 741, 82.61 |
| both | 95,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 528, 16.84; median 12, 0.90 / 734, 82.14 |
| both | 100,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 7, 1.55 / 522, 16.45; median 13, 0.91 / 727, 82.13 |
| both | 105,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 9, 1.88 / 483, 16.11; median 14, 0.91 / 667, 82.12 |
| both | 110,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 11, 1.90 / 479, 16.10; median 15, 0.92 / 661, 82.11 |
| both | 115,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 472, 16.05; median 15, 0.92 / 655, 82.10 |
| both | 120,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 13, 1.93 / 467, 15.95; median 19, 1.11 / 645, 81.90 |

### V1u: per seller split gas (g*_FI: FairBind measured call, g*: same call; own call gas than split if large FI cheaper)

| case | window | seller | tier | own call | g*_FI | g* |
|---|---|---|---|---|---|---|
| lower | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 84,373 | 84,276 |
| lower | busy | OneSource | SP0 | 604,522 | 53,922 | 51,547 |
| lower | busy | CoinMarketCap | RS3 | 86,824 | 206,313 | 207,520 |
| lower | busy | StableApify | RS3 | 86,824 | 195,669 | 197,384 |
| lower | busy | Exa(0.001 or less) | RS3 | 86,824 | 613,880 | 614,408 |
| lower | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 287,497 | 287,791 |
| lower | busy | BlockRun | TEE | 36,440 | 195,643 | 197,392 |
| lower | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 93,234 | 93,476 |
| lower | median | OneSource | SP0 | 604,522 | 63,687 | 61,763 |
| lower | median | CoinMarketCap | RS3 | 86,824 | 284,575 | 286,572 |
| lower | median | StableApify | RS3 | 86,824 | 388,222 | 391,751 |
| lower | median | Exa(0.001 or less) | RS3 | 86,824 | 609,701 | 610,224 |
| lower | median | CoinStats(0.01 or less) | RS3 | 86,824 | 316,703 | 316,933 |
| lower | median | BlockRun | TEE | 36,440 | 542,719 | 556,717 |
| lower | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 74,244 | 73,907 |
| lower | quiet | OneSource | SP0 | 604,522 | 75,734 | 72,523 |
| lower | quiet | CoinMarketCap | RS3 | 86,824 | 484,555 | 488,573 |
| lower | quiet | StableApify | RS3 | 86,824 | 443,809 | 447,135 |
| lower | quiet | Exa(0.001 or less) | RS3 | 86,824 | 732,528 | 733,174 |
| lower | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 239,925 | 240,078 |
| lower | quiet | BlockRun | TEE | 36,440 | 130,010 | 139,053 |
| upper | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 79,474 | 79,183 |
| upper | busy | OneSource | SP0 | 724,426 | 49,126 | 46,212 |
| upper | busy | CoinMarketCap | RS3 | 86,824 | 201,082 | 202,236 |
| upper | busy | StableApify | RS3 | 86,824 | 191,024 | 192,666 |
| upper | busy | Exa(0.001 or less) | RS3 | 86,824 | 608,956 | 609,479 |
| upper | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 284,452 | 284,742 |
| upper | busy | BlockRun | TEE | 36,440 | 190,399 | 192,090 |
| upper | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 88,314 | 88,370 |
| upper | median | OneSource | SP0 | 724,426 | 58,781 | 56,412 |
| upper | median | CoinMarketCap | RS3 | 86,824 | 279,960 | 281,911 |
| upper | median | StableApify | RS3 | 86,824 | 384,918 | 388,409 |
| upper | median | Exa(0.001 or less) | RS3 | 86,824 | 604,724 | 605,242 |
| upper | median | CoinStats(0.01 or less) | RS3 | 86,824 | 315,059 | 315,287 |
| upper | median | BlockRun | TEE | 36,440 | 537,678 | 551,535 |
| upper | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 69,195 | 68,723 |
| upper | quiet | OneSource | SP0 | 724,426 | 71,166 | 67,199 |
| upper | quiet | CoinMarketCap | RS3 | 86,824 | 480,398 | 484,374 |
| upper | quiet | StableApify | RS3 | 86,824 | 442,556 | 445,870 |
| upper | quiet | Exa(0.001 or less) | RS3 | 86,824 | 727,746 | 728,388 |
| upper | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 244,037 | 244,194 |
| upper | quiet | BlockRun | TEE | 36,440 | 125,741 | 134,372 |
| facilitator | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 84,373 | 84,276 |
| facilitator | busy | OneSource | SP0 | 604,522 | 53,922 | 51,547 |
| facilitator | busy | CoinMarketCap | RS3 | 86,824 | 206,313 | 207,520 |
| facilitator | busy | StableApify | RS3 | 86,824 | 195,669 | 197,384 |
| facilitator | busy | Exa(0.001 or less) | RS3 | 86,824 | 613,880 | 614,408 |
| facilitator | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 287,497 | 287,791 |
| facilitator | busy | BlockRun | TEE | 36,440 | 195,643 | 197,392 |
| facilitator | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 93,234 | 93,476 |
| facilitator | median | OneSource | SP0 | 604,522 | 63,687 | 61,763 |
| facilitator | median | CoinMarketCap | RS3 | 86,824 | 284,575 | 286,572 |
| facilitator | median | StableApify | RS3 | 86,824 | 388,222 | 391,751 |
| facilitator | median | Exa(0.001 or less) | RS3 | 86,824 | 609,701 | 610,224 |
| facilitator | median | CoinStats(0.01 or less) | RS3 | 86,824 | 316,703 | 316,933 |
| facilitator | median | BlockRun | TEE | 36,440 | 542,719 | 556,717 |
| facilitator | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 74,244 | 73,907 |
| facilitator | quiet | OneSource | SP0 | 604,522 | 75,734 | 72,523 |
| facilitator | quiet | CoinMarketCap | RS3 | 86,824 | 484,555 | 488,573 |
| facilitator | quiet | StableApify | RS3 | 86,824 | 443,809 | 447,135 |
| facilitator | quiet | Exa(0.001 or less) | RS3 | 86,824 | 732,528 | 733,174 |
| facilitator | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 239,925 | 240,078 |
| facilitator | quiet | BlockRun | TEE | 36,440 | 130,010 | 139,053 |

### V1u: FI-batch (lower, V 1; tier 1a sellers only bundle, six FI sum / (A) share / (B) share, payee (A) share / (B) share)

| G_B | g_b | busy | median | quiet | payee |
|---|---|---|---|---|---|
| 21,000 | 1,000 | 8.73 / 0.00 / 97.97 | 29.99 / 0.00 / 93.12 | 18.64 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.21 |
| 21,000 | 2,500 | 8.84 / 0.00 / 97.97 | 30.09 / 0.00 / 93.12 | 18.77 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.21 |
| 21,000 | 5,000 | 9.00 / 0.00 / 97.97 | 30.25 / 0.00 / 93.12 | 18.99 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.20 |
| 21,000 | 10,315 | 9.36 / 0.00 / 97.97 | 30.58 / 0.00 / 93.12 | 19.45 / 0.00 / 93.36 | busy 0.00 / 99.20; median 0.00 / 99.08 |
| 21,000 | 20,000 | 10.02 / 0.00 / 97.97 | 31.18 / 0.00 / 93.12 | 20.29 / 0.00 / 93.36 | busy 0.00 / 82.49; median 0.00 / 83.44 |
| 21,000 | 31,315 | 10.78 / 0.00 / 94.94 | 31.89 / 0.00 / 93.12 | 21.28 / 0.00 / 93.36 | busy 0.00 / 18.57; median 0.00 / 83.25 |
| 31,315 | 1,000 | 8.75 / 0.00 / 97.97 | 30.01 / 0.00 / 93.12 | 18.65 / 0.00 / 93.36 | busy 0.00 / 99.32; median 0.00 / 99.21 |
| 31,315 | 2,500 | 8.85 / 0.00 / 97.97 | 30.10 / 0.00 / 93.12 | 18.78 / 0.00 / 93.36 | busy 0.00 / 99.32; median 0.00 / 99.20 |
| 31,315 | 5,000 | 9.02 / 0.00 / 97.97 | 30.26 / 0.00 / 93.12 | 19.00 / 0.00 / 93.36 | busy 0.00 / 99.30; median 0.00 / 99.19 |
| 31,315 | 10,315 | 9.38 / 0.00 / 97.97 | 30.59 / 0.00 / 93.12 | 19.46 / 0.00 / 93.36 | busy 0.00 / 99.17; median 0.00 / 99.04 |
| 31,315 | 20,000 | 10.03 / 0.00 / 97.77 | 31.20 / 0.00 / 93.12 | 20.30 / 0.00 / 93.36 | busy 0.00 / 82.49; median 0.00 / 83.43 |
| 31,315 | 31,315 | 10.80 / 0.00 / 94.94 | 31.90 / 0.00 / 93.12 | 21.29 / 0.00 / 93.36 | busy 0.00 / 18.56; median 0.00 / 83.24 |
| 55,509 | 1,000 | 8.78 / 0.00 / 97.97 | 30.03 / 0.00 / 93.12 | 18.66 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.20 |
| 55,509 | 2,500 | 8.88 / 0.00 / 97.97 | 30.13 / 0.00 / 93.12 | 18.79 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.20 |
| 55,509 | 5,000 | 9.05 / 0.00 / 97.97 | 30.28 / 0.00 / 93.12 | 19.01 / 0.00 / 93.36 | busy 0.00 / 99.29; median 0.00 / 99.19 |
| 55,509 | 10,315 | 9.41 / 0.00 / 97.97 | 30.62 / 0.00 / 93.12 | 19.48 / 0.00 / 93.36 | busy 0.00 / 99.16; median 0.00 / 99.03 |
| 55,509 | 20,000 | 10.06 / 0.00 / 97.77 | 31.22 / 0.00 / 93.12 | 20.32 / 0.00 / 93.36 | busy 0.00 / 82.48; median 0.00 / 83.42 |
| 55,509 | 31,315 | 10.83 / 0.00 / 94.94 | 31.93 / 0.00 / 93.12 | 21.31 / 0.00 / 93.36 | busy 0.00 / 18.55; median 0.00 / 83.23 |
| 86,824 | 1,000 | 8.81 / 0.00 / 97.97 | 30.07 / 0.00 / 93.12 | 18.68 / 0.00 / 93.36 | busy 0.00 / 99.30; median 0.00 / 99.19 |
| 86,824 | 2,500 | 8.91 / 0.00 / 97.97 | 30.16 / 0.00 / 93.12 | 18.82 / 0.00 / 93.36 | busy 0.00 / 99.30; median 0.00 / 99.18 |
| 86,824 | 5,000 | 9.08 / 0.00 / 97.97 | 30.32 / 0.00 / 93.12 | 19.03 / 0.00 / 93.36 | busy 0.00 / 99.20; median 0.00 / 99.18 |
| 86,824 | 10,315 | 9.44 / 0.00 / 97.77 | 30.65 / 0.00 / 93.12 | 19.50 / 0.00 / 93.36 | busy 0.00 / 99.14; median 0.00 / 99.00 |
| 86,824 | 20,000 | 10.09 / 0.00 / 94.94 | 31.26 / 0.00 / 93.12 | 20.35 / 0.00 / 93.36 | busy 0.00 / 82.45; median 0.00 / 83.40 |
| 86,824 | 31,315 | 10.86 / 0.00 / 94.94 | 31.97 / 0.00 / 93.12 | 21.33 / 0.00 / 93.36 | busy 0.00 / 18.54; median 0.00 / 83.22 |

### V1: FI point, six seller sum (lower, V 1)

| point | window | FB sum | FI sum | mixed | (A) FB cheaper and ≤10%: seller, revenue share | (B) FI cheaper and ≤10%: seller, revenue share |
|---|---|---|---|---|---|---|
| pt|same | busy | 9.19 | 14.47 | 8.13 | StableEnrich(Out candidates excluded); 94.94 | none; 0.00 |
| pt|same | median | 11.67 | 35.31 | 10.89 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|same | quiet | 11.89 | 26.06 | 11.38 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |
| pt|own_lo | busy | 9.19 | 10.10 | 4.53 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_lo | median | 11.67 | 29.33 | 7.41 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_lo | quiet | 11.89 | 19.80 | 7.64 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_a | busy | 9.19 | 11.22 | 5.50 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_a | median | 11.67 | 30.87 | 8.31 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_a | quiet | 11.89 | 21.41 | 8.88 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_b | busy | 9.19 | 13.35 | 7.32 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_b | median | 11.67 | 33.78 | 10.00 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_b | quiet | 11.89 | 24.46 | 11.23 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_bind_a | busy | 9.19 | 11.91 | 6.09 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_bind_a | median | 11.67 | 31.81 | 8.85 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_bind_a | quiet | 11.89 | 22.39 | 9.64 | none; 0.00 | StableEnrich(Out candidates excluded); 93.36 |
| pt|own_bind_b | busy | 9.19 | 14.04 | 7.91 | none; 0.00 | StableEnrich(Out candidates excluded); 94.94 |
| pt|own_bind_b | median | 11.67 | 34.71 | 10.54 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| pt|own_bind_b | quiet | 11.89 | 25.43 | 11.38 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |
| teeW | busy | 9.19 | 14.47 | 8.13 | StableEnrich(Out candidates excluded); 94.94 | none; 0.00 |
| teeW | median | 11.67 | 35.31 | 10.89 | none; 0.00 | StableEnrich(Out candidates excluded); 93.12 |
| teeW | quiet | 11.89 | 26.06 | 11.38 | StableEnrich(Out candidates excluded); 93.36 | none; 0.00 |

### V1: g grid (lower, V 1; form fi: FairBind measured call)

| form | g | six (A) share / (B) share busy | six (A) share / (B) share median | six (A) share / (B) share quiet | BlockRun region | payee (A) count, share / (B) count, share |
|---|---|---|---|---|---|---|
| fi | 20,000 | 0.00 / 97.97 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 681, 82.51; median 0, 0.00 / 989, 83.46 |
| fi | 25,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 674, 18.79; median 0, 0.00 / 977, 83.43 |
| fi | 30,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 664, 18.59; median 0, 0.00 / 959, 83.26 |
| fi | 31,315 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 622, 18.57; median 0, 0.00 / 869, 83.26 |
| fi | 35,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 618, 18.57; median 0, 0.00 / 861, 83.26 |
| fi | 40,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 610, 18.56; median 0, 0.00 / 853, 83.24 |
| fi | 45,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 609, 18.56; median 0, 0.00 / 841, 83.23 |
| fi | 45,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 609, 18.56; median 0, 0.00 / 840, 83.23 |
| fi | 50,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 604, 18.55; median 0, 0.00 / 836, 83.22 |
| fi | 54,311 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 597, 18.50; median 0, 0.00 / 826, 83.22 |
| fi | 55,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 595, 18.50; median 0, 0.00 / 824, 83.22 |
| fi | 60,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 589, 18.25; median 1, 0.01 / 811, 83.18 |
| fi | 65,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 585, 18.02; median 1, 0.01 / 802, 83.16 |
| fi | 70,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 574, 17.93; median 3, 0.02 / 790, 83.08 |
| fi | 72,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 549, 17.93; median 5, 0.19 / 770, 82.87 |
| fi | 75,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 546, 17.92; median 5, 0.19 / 765, 82.87 |
| fi | 80,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 543, 17.76; median 7, 0.25 / 756, 82.81 |
| fi | 81,311 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 543, 17.76; median 7, 0.25 / 754, 82.81 |
| fi | 85,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 539, 16.87; median 8, 0.25 / 752, 82.81 |
| fi | 86,824 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 537, 16.86; median 9, 0.25 / 749, 82.80 |
| fi | 90,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 535, 16.86; median 11, 0.45 / 747, 82.61 |
| fi | 95,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 532, 16.85; median 12, 0.90 / 741, 82.15 |
| fi | 100,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 7, 1.55 / 527, 16.45; median 13, 0.91 / 733, 82.13 |
| fi | 105,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 9, 1.88 / 523, 16.12; median 14, 0.91 / 725, 82.12 |
| fi | 110,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 516, 16.09; median 15, 0.92 / 720, 82.11 |
| fi | 115,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 478, 16.05; median 16, 0.93 / 661, 82.09 |
| fi | 120,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 17, 2.24 / 471, 15.65; median 19, 1.11 / 651, 81.90 |
| both | 20,000 | 0.00 / 97.97 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 681, 82.51; median 0, 0.00 / 989, 83.46 |
| both | 25,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 674, 18.79; median 0, 0.00 / 977, 83.43 |
| both | 30,000 | 0.00 / 95.13 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 664, 18.59; median 0, 0.00 / 959, 83.26 |
| both | 31,315 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 622, 18.57; median 0, 0.00 / 869, 83.26 |
| both | 35,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 618, 18.57; median 0, 0.00 / 861, 83.26 |
| both | 40,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 610, 18.56; median 0, 0.00 / 853, 83.24 |
| both | 45,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 609, 18.56; median 0, 0.00 / 841, 83.23 |
| both | 45,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 609, 18.56; median 0, 0.00 / 840, 83.23 |
| both | 50,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 0, 0.00 / 604, 18.55; median 0, 0.00 / 836, 83.22 |
| both | 54,311 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 596, 18.26; median 0, 0.00 / 826, 83.22 |
| both | 55,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 594, 18.26; median 1, 0.01 / 823, 83.21 |
| both | 60,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 589, 18.25; median 1, 0.01 / 811, 83.18 |
| both | 65,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 1, 0.24 / 585, 18.02; median 1, 0.01 / 802, 83.16 |
| both | 70,000 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 574, 17.93; median 4, 0.05 / 789, 83.05 |
| both | 72,615 | 0.00 / 94.94 | 0.00 / 93.12 | 0.00 / 93.36 | C_fi, B, B | busy 3, 0.26 / 549, 17.93; median 5, 0.19 / 770, 82.87 |
| both | 75,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 546, 17.92; median 6, 0.25 / 764, 82.81 |
| both | 80,000 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 543, 17.76; median 7, 0.25 / 756, 82.81 |
| both | 81,311 | 0.00 / 94.94 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 3, 0.26 / 543, 17.76; median 7, 0.25 / 754, 82.81 |
| both | 85,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 539, 16.87; median 8, 0.25 / 752, 82.81 |
| both | 86,824 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 4, 1.16 / 537, 16.86; median 9, 0.25 / 749, 82.80 |
| both | 90,000 | 94.94 / 0.00 | 0.00 / 93.12 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 535, 16.86; median 11, 0.45 / 747, 82.61 |
| both | 95,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 5, 1.16 / 532, 16.85; median 12, 0.90 / 741, 82.15 |
| both | 100,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 7, 1.55 / 527, 16.45; median 13, 0.91 / 733, 82.13 |
| both | 105,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 9, 1.88 / 523, 16.12; median 14, 0.91 / 725, 82.12 |
| both | 110,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 11, 1.90 / 517, 16.10; median 15, 0.92 / 720, 82.11 |
| both | 115,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 12, 1.90 / 478, 16.05; median 15, 0.92 / 662, 82.11 |
| both | 120,000 | 94.94 / 0.00 | 93.12 / 0.00 | 93.36 / 0.00 | C_fi, B, B | busy 13, 1.93 / 475, 15.97; median 19, 1.11 / 651, 81.90 |

### V1: per seller split gas (g*_FI: FairBind measured call, g*: same call; own call gas than split if large FI cheaper)

| case | window | seller | tier | own call | g*_FI | g* |
|---|---|---|---|---|---|---|
| lower | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 84,371 | 84,274 |
| lower | busy | OneSource | SP0 | 604,522 | 53,921 | 51,545 |
| lower | busy | CoinMarketCap | RS3 | 86,824 | 206,309 | 207,516 |
| lower | busy | StableApify | RS3 | 86,824 | 195,665 | 197,380 |
| lower | busy | Exa(0.001 or less) | RS3 | 86,824 | 613,869 | 614,397 |
| lower | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 287,491 | 287,786 |
| lower | busy | BlockRun | TEE | 36,440 | 195,642 | 197,391 |
| lower | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 93,232 | 93,474 |
| lower | median | OneSource | SP0 | 604,522 | 63,685 | 61,761 |
| lower | median | CoinMarketCap | RS3 | 86,824 | 284,570 | 286,567 |
| lower | median | StableApify | RS3 | 86,824 | 388,215 | 391,744 |
| lower | median | Exa(0.001 or less) | RS3 | 86,824 | 609,690 | 610,213 |
| lower | median | CoinStats(0.01 or less) | RS3 | 86,824 | 316,697 | 316,927 |
| lower | median | BlockRun | TEE | 36,440 | 542,719 | 556,716 |
| lower | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 74,242 | 73,905 |
| lower | quiet | OneSource | SP0 | 604,522 | 75,732 | 72,521 |
| lower | quiet | CoinMarketCap | RS3 | 86,824 | 484,546 | 488,564 |
| lower | quiet | StableApify | RS3 | 86,824 | 443,801 | 447,127 |
| lower | quiet | Exa(0.001 or less) | RS3 | 86,824 | 732,515 | 733,161 |
| lower | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 239,921 | 240,074 |
| lower | quiet | BlockRun | TEE | 36,440 | 130,008 | 139,051 |
| upper | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 79,472 | 79,181 |
| upper | busy | OneSource | SP0 | 724,426 | 49,124 | 46,211 |
| upper | busy | CoinMarketCap | RS3 | 86,824 | 201,078 | 202,232 |
| upper | busy | StableApify | RS3 | 86,824 | 191,020 | 192,662 |
| upper | busy | Exa(0.001 or less) | RS3 | 86,824 | 608,945 | 609,468 |
| upper | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 284,447 | 284,737 |
| upper | busy | BlockRun | TEE | 36,440 | 190,398 | 192,090 |
| upper | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 88,312 | 88,368 |
| upper | median | OneSource | SP0 | 724,426 | 58,779 | 56,411 |
| upper | median | CoinMarketCap | RS3 | 86,824 | 279,955 | 281,906 |
| upper | median | StableApify | RS3 | 86,824 | 384,911 | 388,402 |
| upper | median | Exa(0.001 or less) | RS3 | 86,824 | 604,713 | 605,231 |
| upper | median | CoinStats(0.01 or less) | RS3 | 86,824 | 315,053 | 315,282 |
| upper | median | BlockRun | TEE | 36,440 | 537,677 | 551,534 |
| upper | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 69,194 | 68,722 |
| upper | quiet | OneSource | SP0 | 724,426 | 71,164 | 67,197 |
| upper | quiet | CoinMarketCap | RS3 | 86,824 | 480,390 | 484,365 |
| upper | quiet | StableApify | RS3 | 86,824 | 442,548 | 445,862 |
| upper | quiet | Exa(0.001 or less) | RS3 | 86,824 | 727,733 | 728,375 |
| upper | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 244,033 | 244,190 |
| upper | quiet | BlockRun | TEE | 36,440 | 125,740 | 134,370 |
| facilitator | busy | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 84,371 | 84,274 |
| facilitator | busy | OneSource | SP0 | 604,522 | 53,921 | 51,545 |
| facilitator | busy | CoinMarketCap | RS3 | 86,824 | 206,309 | 207,516 |
| facilitator | busy | StableApify | RS3 | 86,824 | 195,665 | 197,380 |
| facilitator | busy | Exa(0.001 or less) | RS3 | 86,824 | 613,869 | 614,397 |
| facilitator | busy | CoinStats(0.01 or less) | RS3 | 86,824 | 287,491 | 287,786 |
| facilitator | busy | BlockRun | TEE | 36,440 | 195,642 | 197,391 |
| facilitator | median | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 93,232 | 93,474 |
| facilitator | median | OneSource | SP0 | 604,522 | 63,685 | 61,761 |
| facilitator | median | CoinMarketCap | RS3 | 86,824 | 284,570 | 286,567 |
| facilitator | median | StableApify | RS3 | 86,824 | 388,215 | 391,744 |
| facilitator | median | Exa(0.001 or less) | RS3 | 86,824 | 609,690 | 610,213 |
| facilitator | median | CoinStats(0.01 or less) | RS3 | 86,824 | 316,697 | 316,927 |
| facilitator | median | BlockRun | TEE | 36,440 | 542,719 | 556,716 |
| facilitator | quiet | StableEnrich(Out candidates excluded) | RS3 | 86,824 | 74,242 | 73,905 |
| facilitator | quiet | OneSource | SP0 | 604,522 | 75,732 | 72,521 |
| facilitator | quiet | CoinMarketCap | RS3 | 86,824 | 484,546 | 488,564 |
| facilitator | quiet | StableApify | RS3 | 86,824 | 443,801 | 447,127 |
| facilitator | quiet | Exa(0.001 or less) | RS3 | 86,824 | 732,515 | 733,161 |
| facilitator | quiet | CoinStats(0.01 or less) | RS3 | 86,824 | 239,921 | 240,074 |
| facilitator | quiet | BlockRun | TEE | 36,440 | 130,008 | 139,051 |

### V1: FI-batch (lower, V 1; tier 1a sellers only bundle, six FI sum / (A) share / (B) share, payee (A) share / (B) share)

| G_B | g_b | busy | median | quiet | payee |
|---|---|---|---|---|---|
| 21,000 | 1,000 | 8.71 / 0.00 / 97.97 | 29.96 / 0.00 / 93.12 | 18.61 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.22 |
| 21,000 | 2,500 | 8.81 / 0.00 / 97.97 | 30.05 / 0.00 / 93.12 | 18.74 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.21 |
| 21,000 | 5,000 | 8.98 / 0.00 / 97.97 | 30.21 / 0.00 / 93.12 | 18.95 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.20 |
| 21,000 | 10,315 | 9.34 / 0.00 / 97.97 | 30.54 / 0.00 / 93.12 | 19.42 / 0.00 / 93.36 | busy 0.00 / 99.20; median 0.00 / 99.08 |
| 21,000 | 20,000 | 9.99 / 0.00 / 97.97 | 31.15 / 0.00 / 93.12 | 20.26 / 0.00 / 93.36 | busy 0.00 / 82.49; median 0.00 / 83.45 |
| 21,000 | 31,315 | 10.76 / 0.00 / 94.94 | 31.86 / 0.00 / 93.12 | 21.25 / 0.00 / 93.36 | busy 0.00 / 18.57; median 0.00 / 83.26 |
| 31,315 | 1,000 | 8.73 / 0.00 / 97.97 | 29.97 / 0.00 / 93.12 | 18.61 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.21 |
| 31,315 | 2,500 | 8.83 / 0.00 / 97.97 | 30.07 / 0.00 / 93.12 | 18.74 / 0.00 / 93.36 | busy 0.00 / 99.33; median 0.00 / 99.21 |
| 31,315 | 5,000 | 9.00 / 0.00 / 97.97 | 30.22 / 0.00 / 93.12 | 18.96 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.20 |
| 31,315 | 10,315 | 9.35 / 0.00 / 97.97 | 30.56 / 0.00 / 93.12 | 19.43 / 0.00 / 93.36 | busy 0.00 / 99.20; median 0.00 / 99.08 |
| 31,315 | 20,000 | 10.01 / 0.00 / 97.97 | 31.16 / 0.00 / 93.12 | 20.27 / 0.00 / 93.36 | busy 0.00 / 82.49; median 0.00 / 83.44 |
| 31,315 | 31,315 | 10.77 / 0.00 / 94.94 | 31.87 / 0.00 / 93.12 | 21.25 / 0.00 / 93.36 | busy 0.00 / 18.57; median 0.00 / 83.25 |
| 55,509 | 1,000 | 8.76 / 0.00 / 97.97 | 30.00 / 0.00 / 93.12 | 18.63 / 0.00 / 93.36 | busy 0.00 / 99.32; median 0.00 / 99.20 |
| 55,509 | 2,500 | 8.86 / 0.00 / 97.97 | 30.09 / 0.00 / 93.12 | 18.76 / 0.00 / 93.36 | busy 0.00 / 99.32; median 0.00 / 99.20 |
| 55,509 | 5,000 | 9.03 / 0.00 / 97.97 | 30.25 / 0.00 / 93.12 | 18.98 / 0.00 / 93.36 | busy 0.00 / 99.30; median 0.00 / 99.19 |
| 55,509 | 10,315 | 9.39 / 0.00 / 97.97 | 30.58 / 0.00 / 93.12 | 19.44 / 0.00 / 93.36 | busy 0.00 / 99.17; median 0.00 / 99.03 |
| 55,509 | 20,000 | 10.04 / 0.00 / 97.77 | 31.19 / 0.00 / 93.12 | 20.29 / 0.00 / 93.36 | busy 0.00 / 82.48; median 0.00 / 83.43 |
| 55,509 | 31,315 | 10.81 / 0.00 / 94.94 | 31.90 / 0.00 / 93.12 | 21.27 / 0.00 / 93.36 | busy 0.00 / 18.56; median 0.00 / 83.24 |
| 86,824 | 1,000 | 8.79 / 0.00 / 97.97 | 30.03 / 0.00 / 93.12 | 18.65 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.19 |
| 86,824 | 2,500 | 8.89 / 0.00 / 97.97 | 30.13 / 0.00 / 93.12 | 18.78 / 0.00 / 93.36 | busy 0.00 / 99.31; median 0.00 / 99.18 |
| 86,824 | 5,000 | 9.06 / 0.00 / 97.97 | 30.29 / 0.00 / 93.12 | 19.00 / 0.00 / 93.36 | busy 0.00 / 99.20; median 0.00 / 99.18 |
| 86,824 | 10,315 | 9.42 / 0.00 / 97.77 | 30.62 / 0.00 / 93.12 | 19.46 / 0.00 / 93.36 | busy 0.00 / 99.15; median 0.00 / 99.01 |
| 86,824 | 20,000 | 10.08 / 0.00 / 94.94 | 31.22 / 0.00 / 93.12 | 20.31 / 0.00 / 93.36 | busy 0.00 / 82.45; median 0.00 / 83.41 |
| 86,824 | 31,315 | 10.84 / 0.00 / 94.94 | 31.93 / 0.00 / 93.12 | 21.30 / 0.00 / 93.36 | busy 0.00 / 18.55; median 0.00 / 83.23 |

## 3. (b) w sensitivity and matter outage


### V1u: w grid (V 1; six seller sum lower / upper / facilitator, per window; FI sum lower; BlockRun lower)

| w | six busy | six median | six quiet | FI six lower | BlockRun lower |
|---|---|---|---|---|---|
| 0 (0) | 8.45 / 8.73 / 13.39* | 11.07* / 11.43* / 17.82* | 11.34* / 11.76* / 18.38* | 14.32 / 35.17 / 25.92 | 11.83* / 3.46 / 2.24 |
| w0/10 (0.000173) | 8.52 / 8.81 / 13.47* | 11.14* / 11.49* / 17.89* | 11.40* / 11.82* / 18.44* | 14.34 / 35.19 / 25.93 | 16.25* / 7.23 / 2.41 |
| wf1 (0.000217) | 8.54 / 8.83 / 13.49* | 11.15* / 11.51* / 17.90* | 11.41* / 11.83* / 18.45* | 14.34 / 35.19 / 25.94 | 17.34* / 8.17 / 2.45 |
| w0/3 (0.000577) | 8.70 / 8.99 / 13.65* | 11.28* / 11.64* / 18.03* | 11.53* / 11.95* / 18.58* | 14.38 / 35.23 / 25.97 | 25.83* / 15.49* / 2.80 |
| w0 (0.00173) | 9.21 / 9.50 / 14.16* | 11.70* / 12.06* / 18.45* | 11.92* / 12.34* / 18.96* | 14.50 / 35.34 / 26.09 | 48.26* / 35.42* / 3.91 |
| 0.002 (0.002) | 9.33 / 9.62 / 14.28* | 11.80* / 12.15* / 18.55* | 12.01* / 12.43* / 19.05* | 14.52 / 35.37 / 26.12 | 52.62* / 39.40* / 4.16 |
| 3w0 (0.00519) | 10.74* / 11.02* / 15.68* | 12.95* / 13.31* / 19.70* | 13.08* / 13.50* / 20.12* | 14.84 / 35.69 / 26.44 | 86.45* / 72.16* / 7.16 |
| 0.005 (0.005) | 10.65* / 10.94* / 15.60* | 12.88* / 13.24* / 19.63* | 13.01* / 13.44* / 20.06* | 14.82 / 35.67 / 26.42 | 85.12* / 70.78* / 6.99 |
| 0.01 (0.01) | 12.83* / 13.11* / 17.77* | 14.67* / 15.03* / 21.42* | 14.68* / 15.10* / 21.72* | 15.32 / 36.17 / 26.92 | 105.42* / 93.25* / 11.55* |
| 10w0 (0.0173) | 15.95* / 16.24* / 20.89* | 17.25* / 17.61* / 24.00* | 17.08* / 17.50* / 24.12* | 16.05 / 36.90 / 27.65 | 112.45* / 102.50* / 17.89* |

### V1u: per window stall one (L = 2,279 block; six sum lower / upper / facilitator, FI lower, BlockRun lower)

| w | window | six FB | six FI lower | BlockRun FB lower | BlockRun FI lower |
|---|---|---|---|---|---|
| 0 | busy | 8.84 / 9.13 / 13.79* | 14.57 | 12.08* | 13.29 |
| 0 | median | 11.51* / 11.86* / 18.26* | 35.42 | 3.71 | 3.95 |
| 0 | quiet | 12.06* / 12.48* / 19.10* | 26.27 | 2.63 | 1.81 |
| w0 | busy | 9.61 / 9.89 / 14.55* | 14.75 | 48.51* | 13.46 |
| w0 | median | 12.14* / 12.49* / 18.89* | 35.59 | 35.67* | 4.12 |
| w0 | quiet | 12.64* / 13.06* / 19.68* | 26.44 | 4.29 | 1.98 |

per seller stall term(lower): failure probability P̄(bound seller below~upper), loss USD, adding share, FI refund share.

| window | seller | source | P̄ | loss | FB added | FI added |
|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | own | 0.9984 | 4.62 | 0.32 | 0.25 |
| busy | OneSource | own | 0.3063 | 1.08 | 1.07 | 0.25 |
| busy | CoinMarketCap | own | 0.6174 | 1.11 | 1.57 | 0.25 |
| busy | StableApify | own | 0.0959 | 1.01 | 3.23 | 0.25 |
| busy | Exa(0.001 or less) | address | 0.3285 | 1.00 | 139.86 | 0.25 |
| busy | CoinStats(0.01 or less) | address | 0.0319 | 1.00 | 48.39 | 0.25 |
| busy | BlockRun | own | 1.0000 | 262.37 | 0.25 | 0.25 |
| median | StableEnrich(Out candidates excluded) | own | 0.9990 | 3.82 | 0.34 | 0.25 |
| median | OneSource | own | 0.8248 | 1.20 | 1.22 | 0.25 |
| median | CoinMarketCap | own | 0.0859 | 1.00 | 5.29 | 0.25 |
| median | StableApify | own | 0.0586 | 1.00 | 9.39 | 0.25 |
| median | Exa(0.001 or less) | address | 0.3247 | 1.00 | 121.68 | 0.25 |
| median | CoinStats(0.01 or less) | address | 0.0288 | 1.00 | 102.70 | 0.25 |
| median | BlockRun | own | 1.0000 | 318.35 | 0.25 | 0.25 |
| quiet | StableEnrich(Out candidates excluded) | bound | 0.6001~1.0000 | 3.52 | 0.49 | 0.35 |
| quiet | OneSource | bound | 0.2553~1.0000 | 1.17 | 2.34 | 0.35 |
| quiet | CoinMarketCap | bound | 0.0314~0.2186 | 1.00 | 23.09 | 0.35 |
| quiet | StableApify | bound | 0.0100~0.0538 | 1.00 | 22.43 | 0.35 |
| quiet | Exa(0.001 or less) | bound | 0.0858~0.6289 | 1.00 | 353.51 | 0.35 |
| quiet | CoinStats(0.01 or less) | bound | 0.0045~0.0106 | 1.00 | 96.61 | 0.35 |
| quiet | BlockRun | bound | 0.5843~1.0000 | 10.85 | 0.38 | 0.35 |

### V1u: P10 threshold (lower, d 1; R_e USDC, in parentheses m, k)

| v̄ | w | 10% below end | 10% upper end | 5% end | FI crossing | min cost share |
|---|---|---|---|---|---|---|
| 0.1 | 0 | 0.1961 (1.961, 32) | none | 0.4704 below | 1.582 → FB | 1.48 |
| 0.1 | w0/10 | 0.1971 (1.971, 32) | 67.93 (679.3, 4) | 0.4811 below; 25.99 upper | 2.147 → FB; 6.042 → FI | 2.38 |
| 0.1 | wf1 | 0.1973 (1.973, 32) | 53.97 (539.7, 8) | 0.484 below; 21.71 upper | 2.709 → FB; 3.818 → FI | 2.49 |
| 0.1 | w0/3 | 0.1994 (1.994, 32) | 20.35 (203.5, 1) | 0.51 below; 7.739 upper | none(increase FI) | 3.19 |
| 0.1 | w0 | 0.2067 (2.067, 32) | 6.537 (65.37, 2) | 0.6595 below; 1.992 upper | none(increase FI) | 4.54 |
| 0.1 | 0.002 | 0.2086 (2.086, 32) | 5.609 (56.09, 4) | 0.741 below; 1.537 upper | none(increase FI) | 4.79 |
| 0.1 | 3w0 | 0.2354 (2.354, 32) | 1.911 (19.11, 8) | none | none(increase FI) | 7.03 |
| 0.1 | 0.005 | 0.2335 (2.335, 32) | 2 (20, 8) | none | none(increase FI) | 6.92 |
| 0.1 | 0.01 | 0.3259 (3.259, 32) | 0.7149 (7.149, 32) | none | none(increase FI) | 9.47 |
| 0.1 | 10w0 | none | none | none | none(increase FI) | 12.39 |
| 0.1 | stall_w0 | 0.2178 (2.178, 32) | 6.324 (63.24, 4) | 0.8206 below; 1.631 upper | none(increase FI) | 4.82 |
| 0.02 | 0 | 0.4547 (22.73, 8) | none | none | 0.2735 → FB | 6.54 |
| 0.02 | w0/10 | 0.4643 (23.22, 8) | 25.6 (1280, 8) | none | 0.2751 → FB; 52.01 → FI | 7.26 |
| 0.02 | wf1 | 0.4669 (23.34, 8) | 20.11 (1005, 16) | none | 0.2755 → FB; 41.3 → FI | 7.39 |
| 0.02 | w0/3 | 0.49 (24.5, 8) | 6.157 (307.8, 16) | none | 0.279 → FB; 15.14 → FI | 8.07 |
| 0.02 | w0 | 0.6127 (30.64, 8) | 2.138 (106.9, 2) | none | 0.2914 → FB; 4.569 → FI | 9.41 |
| 0.02 | 0.002 | 0.6861 (34.3, 4) | 1.672 (83.61, 2) | none | 0.2947 → FB; 3.908 → FI | 9.66 |
| 0.02 | 3w0 | none | none | none | 0.3515 → FB; 1.263 → FI | 11.90 |
| 0.02 | 0.005 | none | none | none | 0.3466 → FB; 1.329 → FI | 11.80 |
| 0.02 | 0.01 | none | none | none | none(increase FI) | 14.34 |
| 0.02 | 10w0 | none | none | none | none(increase FI) | 17.28 |
| 0.02 | stall_w0 | 0.7474 (37.37, 4) | 1.807 (90.34, 2) | none | 0.2974 → FB; 4.565 → FI | 9.69 |

### V1: w grid (V 1; six seller sum lower / upper / facilitator, per window; FI sum lower; BlockRun lower)

| w | six busy | six median | six quiet | FI six lower | BlockRun lower |
|---|---|---|---|---|---|
| 0 (0) | 8.42 / 8.66 / 13.37* | 11.04* / 11.34* / 17.79* | 11.30* / 11.67* / 18.35* | 14.30 / 35.13 / 25.88 | 11.82* / 3.46 / 2.24 |
| w0/10 (0.000173) | 8.50 / 8.73 / 13.44* | 11.10* / 11.40* / 17.85* | 11.36* / 11.73* / 18.41* | 14.31 / 35.15 / 25.90 | 16.24* / 7.23 / 2.41 |
| wf1 (0.000217) | 8.52 / 8.75 / 13.46* | 11.12* / 11.42* / 17.87* | 11.38* / 11.75* / 18.42* | 14.32 / 35.16 / 25.90 | 17.33* / 8.16 / 2.45 |
| w0/3 (0.000577) | 8.68 / 8.91 / 13.62* | 11.25* / 11.55* / 18.00* | 11.50* / 11.87* / 18.54* | 14.35 / 35.19 / 25.94 | 25.82* / 15.49* / 2.80 |
| w0 (0.00173) | 9.19 / 9.42 / 14.13* | 11.67* / 11.97* / 18.42* | 11.89* / 12.26* / 18.93* | 14.47 / 35.31 / 26.06 | 48.25* / 35.42* / 3.90 |
| 0.002 (0.002) | 9.31 / 9.54 / 14.25* | 11.76* / 12.06* / 18.52* | 11.98* / 12.35* / 19.02* | 14.50 / 35.33 / 26.08 | 52.61* / 39.39* / 4.16 |
| 3w0 (0.00519) | 10.71* / 10.95* / 15.65* | 12.92* / 13.22* / 19.67* | 13.04* / 13.42* / 20.09* | 14.82 / 35.65 / 26.40 | 86.44* / 72.15* / 7.16 |
| 0.005 (0.005) | 10.63* / 10.86* / 15.57* | 12.85* / 13.15* / 19.60* | 12.98* / 13.35* / 20.02* | 14.80 / 35.63 / 26.38 | 85.11* / 70.78* / 6.99 |
| 0.01 (0.01) | 12.80* / 13.04* / 17.75* | 14.64* / 14.94* / 21.39* | 14.64* / 15.01* / 21.69* | 15.30 / 36.13 / 26.88 | 105.41* / 93.25* / 11.55* |
| 10w0 (0.0173) | 15.92* / 16.16* / 20.87* | 17.22* / 17.52* / 23.97* | 17.04* / 17.42* / 24.09* | 16.03 / 36.86 / 27.61 | 112.43* / 102.50* / 17.89* |

### V1: per window stall one (L = 2,279 block; six sum lower / upper / facilitator, FI lower, BlockRun lower)

| w | window | six FB | six FI lower | BlockRun FB lower | BlockRun FI lower |
|---|---|---|---|---|---|
| 0 | busy | 8.82 / 9.05 / 13.76* | 14.55 | 12.07* | 13.28 |
| 0 | median | 11.47* / 11.77* / 18.23* | 35.38 | 3.70 | 3.94 |
| 0 | quiet | 12.03* / 12.40* / 19.07* | 26.24 | 2.62 | 1.81 |
| w0 | busy | 9.58 / 9.82 / 14.53* | 14.72 | 48.50* | 13.45 |
| w0 | median | 12.10* / 12.40* / 18.85* | 35.56 | 35.67* | 4.12 |
| w0 | quiet | 12.61* / 12.98* / 19.65* | 26.41 | 4.29 | 1.98 |

per seller stall term(lower): failure probability P̄(bound seller below~upper), loss USD, adding share, FI refund share.

| window | seller | source | P̄ | loss | FB added | FI added |
|---|---|---|---|---|---|---|
| busy | StableEnrich(Out candidates excluded) | own | 0.9984 | 4.62 | 0.32 | 0.25 |
| busy | OneSource | own | 0.3063 | 1.08 | 1.07 | 0.25 |
| busy | CoinMarketCap | own | 0.6174 | 1.11 | 1.57 | 0.25 |
| busy | StableApify | own | 0.0959 | 1.01 | 3.23 | 0.25 |
| busy | Exa(0.001 or less) | address | 0.3285 | 1.00 | 139.86 | 0.25 |
| busy | CoinStats(0.01 or less) | address | 0.0319 | 1.00 | 48.39 | 0.25 |
| busy | BlockRun | own | 1.0000 | 262.37 | 0.25 | 0.25 |
| median | StableEnrich(Out candidates excluded) | own | 0.9990 | 3.82 | 0.34 | 0.25 |
| median | OneSource | own | 0.8248 | 1.20 | 1.22 | 0.25 |
| median | CoinMarketCap | own | 0.0859 | 1.00 | 5.29 | 0.25 |
| median | StableApify | own | 0.0586 | 1.00 | 9.39 | 0.25 |
| median | Exa(0.001 or less) | address | 0.3247 | 1.00 | 121.68 | 0.25 |
| median | CoinStats(0.01 or less) | address | 0.0288 | 1.00 | 102.70 | 0.25 |
| median | BlockRun | own | 1.0000 | 318.35 | 0.25 | 0.25 |
| quiet | StableEnrich(Out candidates excluded) | bound | 0.6001~1.0000 | 3.52 | 0.49 | 0.35 |
| quiet | OneSource | bound | 0.2553~1.0000 | 1.17 | 2.34 | 0.35 |
| quiet | CoinMarketCap | bound | 0.0314~0.2186 | 1.00 | 23.09 | 0.35 |
| quiet | StableApify | bound | 0.0100~0.0538 | 1.00 | 22.43 | 0.35 |
| quiet | Exa(0.001 or less) | bound | 0.0858~0.6289 | 1.00 | 353.51 | 0.35 |
| quiet | CoinStats(0.01 or less) | bound | 0.0045~0.0106 | 1.00 | 96.61 | 0.35 |
| quiet | BlockRun | bound | 0.5843~1.0000 | 10.85 | 0.38 | 0.35 |

### V1: P10 threshold (lower, d 1; R_e USDC, in parentheses m, k)

| v̄ | w | 10% below end | 10% upper end | 5% end | FI crossing | min cost share |
|---|---|---|---|---|---|---|
| 0.1 | 0 | 0.196 (1.96, 32) | none | 0.4701 below | 1.582 → FB | 1.47 |
| 0.1 | w0/10 | 0.197 (1.97, 32) | 67.94 (679.4, 4) | 0.4808 below; 26 upper | 2.147 → FB; 6.042 → FI | 2.38 |
| 0.1 | wf1 | 0.1972 (1.972, 32) | 53.98 (539.8, 8) | 0.4837 below; 21.72 upper | 2.708 → FB; 3.819 → FI | 2.49 |
| 0.1 | w0/3 | 0.1993 (1.993, 32) | 20.36 (203.6, 1) | 0.5097 below; 7.744 upper | none(increase FI) | 3.19 |
| 0.1 | w0 | 0.2066 (2.066, 32) | 6.539 (65.39, 2) | 0.6589 below; 1.994 upper | none(increase FI) | 4.54 |
| 0.1 | 0.002 | 0.2084 (2.084, 32) | 5.61 (56.1, 4) | 0.7402 below; 1.538 upper | none(increase FI) | 4.79 |
| 0.1 | 3w0 | 0.2352 (2.352, 32) | 1.911 (19.11, 8) | none | none(increase FI) | 7.03 |
| 0.1 | 0.005 | 0.2333 (2.333, 32) | 2.001 (20.01, 8) | none | none(increase FI) | 6.92 |
| 0.1 | 0.01 | 0.3256 (3.256, 32) | 0.7153 (7.153, 32) | none | none(increase FI) | 9.46 |
| 0.1 | 10w0 | none | none | none | none(increase FI) | 12.39 |
| 0.1 | stall_w0 | 0.2177 (2.177, 32) | 6.325 (63.25, 4) | 0.8187 below; 1.635 upper | none(increase FI) | 4.82 |
| 0.02 | 0 | 0.4536 (22.68, 8) | none | none | 0.2735 → FB | 6.54 |
| 0.02 | w0/10 | 0.4632 (23.16, 8) | 25.6 (1280, 8) | none | 0.2751 → FB; 52.01 → FI | 7.25 |
| 0.02 | wf1 | 0.4658 (23.29, 8) | 20.15 (1008, 8) | none | 0.2755 → FB; 41.3 → FI | 7.38 |
| 0.02 | w0/3 | 0.4888 (24.44, 8) | 6.18 (309, 16) | none | 0.279 → FB; 15.14 → FI | 8.06 |
| 0.02 | w0 | 0.6108 (30.54, 8) | 2.146 (107.3, 2) | none | 0.2914 → FB; 4.569 → FI | 9.41 |
| 0.02 | 0.002 | 0.681 (34.05, 4) | 1.683 (84.16, 2) | none | 0.2947 → FB; 3.908 → FI | 9.66 |
| 0.02 | 3w0 | none | none | none | 0.3515 → FB; 1.263 → FI | 11.90 |
| 0.02 | 0.005 | none | none | none | 0.3465 → FB; 1.329 → FI | 11.79 |
| 0.02 | 0.01 | none | none | none | none(increase FI) | 14.33 |
| 0.02 | 10w0 | none | none | none | none(increase FI) | 17.27 |
| 0.02 | stall_w0 | 0.7419 (37.09, 4) | 1.819 (90.94, 2) | none | 0.2974 → FB; 4.565 → FI | 9.68 |
