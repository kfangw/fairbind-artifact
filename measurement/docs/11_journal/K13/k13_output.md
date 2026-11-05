# K13 output (k13_cost.py)

| input | SHA-256 |
|---|---|
| logs/k13_gas.tsv | 97d05f53514255e058a7404cf74797a507383f56c01e61a431cc51be8f977a6e |
| ../K12/k12.py | 9eda92027042ee43e3eafd402192d1883100be5bdce900def9be0584785abcc1 |
| K13_preregistration.md | 05e4b1428722186d334cceffb75040afb3e0fd55dc51980241ebcbb15e9895fd |

## 1. measured gas (median, run count, run between max difference)

| variant | event | P | m | sig | slot | tx gas | floor | run count | spread |
|---|---|---|---|---|---|---|---|---|---|
| base | anchor_self | 1 | 1 | 0 | fresh | 326021 | 45030 | 3 | 0 |
| base | anchor_self | 1 | 1 | 1 | fresh | 332415 | 47940 | 3 | 0 |
| base | anchor_self | 1 | 16 | 0 | fresh | 629485 | 210540 | 3 | 0 |
| base | anchor_self | 1 | 16 | 1 | fresh | 732911 | 257670 | 3 | 0 |
| base | anchor_self | 1 | 2 | 0 | fresh | 346384 | 56060 | 3 | 0 |
| base | anchor_self | 1 | 2 | 1 | fresh | 359214 | 61910 | 3 | 0 |
| base | anchor_self | 1 | 32 | 0 | fresh | 953893 | 386960 | 3 | 0 |
| base | anchor_self | 1 | 32 | 1 | fresh | 1162206 | 481220 | 3 | 0 |
| base | anchor_self | 1 | 4 | 0 | fresh | 386874 | 78060 | 3 | 0 |
| base | anchor_self | 1 | 4 | 1 | fresh | 412608 | 89820 | 3 | 0 |
| base | anchor_self | 1 | 64 | 0 | fresh | 1607722 | 739680 | 3 | 0 |
| base | anchor_self | 1 | 64 | 1 | fresh | 2030288 | 928140 | 3 | 0 |
| base | anchor_self | 1 | 8 | 0 | fresh | 467716 | 122210 | 3 | 0 |
| base | anchor_self | 1 | 8 | 1 | fresh | 519274 | 145790 | 3 | 0 |
| base | dispute_open | - | - | - | - | 279786 | 42930 | 3 | 0 |
| base | double_sign | - | - | - | - | 139091 | 33500 | 3 | 0 |
| base | prove | - | - | - | - | 95398 | 48330 | 3 | 0 |
| base | release_one | - | - | - | - | 222273 | 22080 | 3 | 0 |
| base | swap_proof | - | - | - | - | 134688 | 54570 | 3 | 0 |
| c1 | anchor_self | 1 | 1 | 0 | fresh | 117437 | 54660 | 3 | 0 |
| c1 | anchor_self | 1 | 1 | 1 | fresh | 123816 | 57600 | 3 | 0 |
| c1 | anchor_self | 1 | 16 | 0 | fresh | 420610 | 220170 | 3 | 0 |
| c1 | anchor_self | 1 | 16 | 1 | fresh | 523600 | 267270 | 3 | 0 |
| c1 | anchor_self | 1 | 2 | 0 | fresh | 137822 | 65750 | 3 | 0 |
| c1 | anchor_self | 1 | 2 | 1 | fresh | 150559 | 71630 | 3 | 0 |
| c1 | anchor_self | 1 | 32 | 0 | fresh | 744737 | 396590 | 3 | 0 |
| c1 | anchor_self | 1 | 32 | 1 | fresh | 952252 | 490850 | 3 | 0 |
| c1 | anchor_self | 1 | 4 | 0 | fresh | 178271 | 87780 | 3 | 0 |
| c1 | anchor_self | 1 | 4 | 1 | fresh | 203842 | 99540 | 3 | 0 |
| c1 | anchor_self | 1 | 64 | 0 | fresh | 1398063 | 749460 | 3 | 0 |
| c1 | anchor_self | 1 | 64 | 1 | fresh | 1818946 | 937890 | 3 | 0 |
| c1 | anchor_self | 1 | 8 | 0 | fresh | 259018 | 131930 | 3 | 0 |
| c1 | anchor_self | 1 | 8 | 1 | fresh | 310291 | 155420 | 3 | 0 |
| c1 | dispute_open | - | - | - | - | 284189 | 51750 | 3 | 0 |
| c1 | double_sign | - | - | - | - | 142610 | 42410 | 3 | 0 |
| c1 | prove | - | - | - | - | 101351 | 57240 | 3 | 0 |
| c1 | release_one | - | - | - | - | 225238 | 22080 | 3 | 0 |
| c1 | swap_proof | - | - | - | - | 137537 | 63360 | 3 | 0 |
| c1r | anchor_self | 1 | 1 | 0 | fresh | 126311 | 54660 | 3 | 0 |
| c1r | anchor_self | 1 | 1 | 0 | reused | 111599 | 54690 | 3 | 0 |
| c1r | anchor_self | 1 | 1 | 1 | fresh | 132689 | 57600 | 3 | 0 |
| c1r | anchor_self | 1 | 1 | 1 | reused | 117977 | 57630 | 3 | 0 |
| c1r | anchor_self | 1 | 16 | 0 | fresh | 429510 | 220170 | 3 | 0 |
| c1r | anchor_self | 1 | 16 | 0 | reused | 414811 | 220170 | 3 | 0 |
| c1r | anchor_self | 1 | 16 | 1 | fresh | 532511 | 267270 | 3 | 0 |
| c1r | anchor_self | 1 | 16 | 1 | reused | 517812 | 267270 | 3 | 0 |
| c1r | anchor_self | 1 | 2 | 0 | fresh | 146697 | 65750 | 3 | 0 |
| c1r | anchor_self | 1 | 2 | 0 | reused | 131986 | 65720 | 3 | 0 |
| c1r | anchor_self | 1 | 2 | 1 | fresh | 159435 | 71630 | 3 | 0 |
| c1r | anchor_self | 1 | 2 | 1 | reused | 144761 | 71630 | 3 | 0 |
| c1r | anchor_self | 1 | 32 | 0 | fresh | 753666 | 396590 | 3 | 0 |
| c1r | anchor_self | 1 | 32 | 0 | reused | 738967 | 396590 | 3 | 0 |
| c1r | anchor_self | 1 | 32 | 1 | fresh | 961201 | 490850 | 3 | 0 |
| c1r | anchor_self | 1 | 32 | 1 | reused | 946502 | 490850 | 3 | 0 |
| c1r | anchor_self | 1 | 4 | 0 | fresh | 187150 | 87780 | 3 | 0 |
| c1r | anchor_self | 1 | 4 | 0 | reused | 172426 | 87780 | 3 | 0 |
| c1r | anchor_self | 1 | 4 | 1 | fresh | 212723 | 99540 | 3 | 0 |
| c1r | anchor_self | 1 | 4 | 1 | reused | 198012 | 99510 | 3 | 0 |
| c1r | anchor_self | 1 | 64 | 0 | fresh | 1407049 | 749460 | 3 | 0 |
| c1r | anchor_self | 1 | 64 | 0 | reused | 1392350 | 749460 | 3 | 0 |
| c1r | anchor_self | 1 | 64 | 1 | fresh | 1827974 | 937890 | 3 | 0 |
| c1r | anchor_self | 1 | 64 | 1 | reused | 1813275 | 937890 | 3 | 0 |
| c1r | anchor_self | 1 | 8 | 0 | fresh | 267903 | 131930 | 3 | 0 |
| c1r | anchor_self | 1 | 8 | 0 | reused | 253204 | 131930 | 3 | 0 |
| c1r | anchor_self | 1 | 8 | 1 | fresh | 319181 | 155420 | 3 | 0 |
| c1r | anchor_self | 1 | 8 | 1 | reused | 304507 | 155420 | 3 | 0 |
| c1r | dispute_open | - | - | - | - | 287514 | 51750 | 3 | 0 |
| c1r | double_sign | - | - | - | - | 147276 | 42410 | 3 | 0 |
| c1r | prove | - | - | - | - | 104676 | 57240 | 3 | 0 |
| c1r | release_one | - | - | - | - | 228217 | 22080 | 3 | 0 |
| c1r | swap_proof | - | - | - | - | 142764 | 63360 | 3 | 0 |

## 2. model entering cell

| cell | K12(G11) | base | c1 | c1r |
|---|---|---|---|---|
| F[1] | 189907.0 | 304963.3 | 96304.0 | 90508.7 |
| M[1] | 21649.4 | 26788.8 | 26748.4 | 26749.8 |
| F[0] | 190538.3 | 305657.0 | 97111.7 | 91283.0 |
| M[0] | 12953.3 | 20257.4 | 20238.3 | 20240.1 |
| FL_F[1] | 34460.0 | 33980.0 | 43610.0 | 43610.0 |
| WRAP | 3252.0 | - | - | - |
| d_prf | 0.0 | 0.0 | 5953.0 | 9278.0 |
| d_cur | 0.0 | 0.0 | 2965.0 | 5944.0 |
| MY (P = 1, 4, 16, 64; G11 1, 2, 4, 8) | +0, -6991, -6745, +4452 | - | - | - |
| leaf one direct / linear fit F+M | - | 332415 / 331752 (-0.20%) | 123816 / 123052 (-0.62%) | 117977 / 117258 (-0.61%) |

## 3. G11 with difference (base row / G11 row)

| cell | base | K12(G11) | difference |
|---|---|---|---|
| F[1] | 304963.3 | 189907.0 | +60.59% |
| F[0] | 305657.0 | 190538.3 | +60.42% |
| M[1] | 26788.8 | 21649.4 | +23.74% |
| M[0] | 20257.4 | 12953.3 | +56.39% |
| WRAP | - | 3252.0 | bundle row none |

## 4. main calculation (difference transplant: K12 cell + same fork variant − reference, scenario S, mode N, V 1, P1)


### median seller(lower / upper) and 10% within seller count(seven among, lower / upper)

| calculation | N | busy | median | quiet | 10% within count lower(busy, median, quiet) | upper |
|---|---|---|---|---|---|---|
| K13-base | 1 | 24.18% / 37.80% | 47.45% / 70.92% | 73.40% / 111.34% | 1, 1, 2 | 1, 1, 2 |
| K13-base | 4 | 19.61% / 24.86% | 33.75% / 39.85% | 51.37% / 61.37% | 1, 1, 2 | 1, 1, 2 |
| K13-base | 16 | 18.44% / 21.59% | 30.25% / 32.01% | 45.74% / 48.75% | 1, 1, 2 | 1, 1, 2 |
| K13-base | 64 | 18.15% / 20.79% | 29.37% / 30.04% | 44.33% / 45.60% | 1, 1, 2 | 1, 1, 2 |
| K13-c1 | 1 | 16.98% / 30.60% | 32.17% / 55.65% | 49.70% / 87.64% | 1, 1, 2 | 1, 1, 2 |
| K13-c1 | 4 | 12.41% / 17.66% | 19.27% / 25.11% | 27.67% / 37.67% | 3, 1, 2 | 1, 1, 2 |
| K13-c1 | 16 | 11.25% / 14.40% | 16.85% / 19.40% | 22.04% / 25.05% | 3, 1, 2 | 2, 1, 2 |
| K13-c1 | 64 | 11.02% / 13.58% | 16.25% / 17.98% | 20.63% / 21.90% | 3, 1, 2 | 2, 1, 2 |
| K13-c1r | 1 | 17.05% / 30.67% | 32.46% / 55.94% | 50.16% / 88.10% | 1, 1, 2 | 1, 1, 2 |
| K13-c1r | 4 | 12.48% / 17.73% | 19.38% / 25.23% | 28.13% / 38.13% | 3, 1, 2 | 1, 1, 2 |
| K13-c1r | 16 | 11.31% / 14.46% | 16.97% / 19.52% | 22.50% / 25.52% | 3, 1, 2 | 2, 1, 2 |
| K13-c1r | 64 | 11.05% / 13.65% | 16.37% / 18.09% | 21.09% / 22.36% | 3, 1, 2 | 2, 1, 2 |

### target seller and set (lower / upper, N = 1 and 64)

| calculation | window | target | N 1 | N 64 |
|---|---|---|---|---|
| K13-base | busy | median seller | 24.18% / 37.80% | 18.15% / 20.79% |
| K13-base | busy | StableApify | 19.66% / 28.42% | 12.92% / 13.17% |
| K13-base | busy | CoinStats(0.01 or less) | 301.21% / 447.59% | 189.98% / 196.03% |
| K13-base | busy | Exa(0.001 or less) | 806.14% / 1412.38% | 471.53% / 551.35% |
| K13-base | busy | BlockRun | 42.05% / 42.10% | 42.04% / 42.07% |
| K13-base | busy | StableEnrich(Out candidates excluded) | 3.67% / 4.89% | 3.17% / 3.44% |
| K13-base | busy | T01t pooled | 4.84% / 6.84% | 3.99% / 4.39% |
| K13-base | median | median seller | 47.45% / 70.92% | 29.37% / 30.04% |
| K13-base | median | StableApify | 51.28% / 77.11% | 31.45% / 32.29% |
| K13-base | median | CoinStats(0.01 or less) | 488.07% / 728.04% | 307.81% / 320.40% |
| K13-base | median | Exa(0.001 or less) | 788.07% / 1402.50% | 460.74% / 547.51% |
| K13-base | median | BlockRun | 33.60% / 33.64% | 33.59% / 33.62% |
| K13-base | median | StableEnrich(Out candidates excluded) | 4.00% / 5.67% | 3.33% / 3.68% |
| K13-base | median | T01t pooled | 5.97% / 8.51% | 4.89% / 5.41% |
| K13-base | quiet | median seller | 73.40% / 111.34% | 44.33% / 45.60% |
| K13-base | quiet | StableApify | 73.40% / 111.23% | 44.72% / 46.37% |
| K13-base | quiet | CoinStats(0.01 or less) | 380.22% / 563.38% | 255.09% / 280.39% |
| K13-base | quiet | Exa(0.001 or less) | 929.62% / 1689.30% | 537.76% / 651.65% |
| K13-base | quiet | BlockRun | 2.70% / 3.10% | 2.54% / 2.64% |
| K13-base | quiet | StableEnrich(Out candidates excluded) | 4.51% / 6.04% | 3.88% / 4.20% |
| K13-base | quiet | T01t pooled | 5.84% / 8.10% | 4.86% / 5.32% |
| K13-c1 | busy | median seller | 16.98% / 30.60% | 11.02% / 13.58% |
| K13-c1 | busy | StableApify | 13.41% / 22.17% | 6.67% / 6.92% |
| K13-c1 | busy | CoinStats(0.01 or less) | 205.10% / 351.47% | 93.86% / 99.92% |
| K13-c1 | busy | Exa(0.001 or less) | 502.49% / 1108.72% | 167.87% / 247.69% |
| K13-c1 | busy | BlockRun | 42.00% / 42.05% | 41.99% / 42.02% |
| K13-c1 | busy | StableEnrich(Out candidates excluded) | 2.99% / 4.21% | 2.49% / 2.76% |
| K13-c1 | busy | T01t pooled | 3.76% / 5.75% | 2.90% / 3.31% |
| K13-c1 | median | median seller | 32.17% / 55.65% | 16.25% / 17.98% |
| K13-c1 | median | StableApify | 34.83% / 60.66% | 15.01% / 15.84% |
| K13-c1 | median | CoinStats(0.01 or less) | 334.30% / 574.27% | 154.04% / 166.63% |
| K13-c1 | median | Exa(0.001 or less) | 486.41% / 1100.84% | 159.08% / 245.85% |
| K13-c1 | median | BlockRun | 33.59% / 33.63% | 33.58% / 33.61% |
| K13-c1 | median | StableEnrich(Out candidates excluded) | 3.07% / 4.73% | 2.39% / 2.74% |
| K13-c1 | median | T01t pooled | 4.53% / 7.08% | 3.45% / 3.98% |
| K13-c1 | quiet | median seller | 49.70% / 87.64% | 20.63% / 21.90% |
| K13-c1 | quiet | StableApify | 49.91% / 87.74% | 21.24% / 22.89% |
| K13-c1 | quiet | CoinStats(0.01 or less) | 267.66% / 450.82% | 142.52% / 167.83% |
| K13-c1 | quiet | Exa(0.001 or less) | 567.57% / 1327.25% | 175.71% / 289.60% |
| K13-c1 | quiet | BlockRun | 2.49% / 2.89% | 2.34% / 2.44% |
| K13-c1 | quiet | StableEnrich(Out candidates excluded) | 3.62% / 5.15% | 2.99% / 3.32% |
| K13-c1 | quiet | T01t pooled | 4.55% / 6.81% | 3.57% / 4.03% |
| K13-c1r | busy | median seller | 17.05% / 30.67% | 11.05% / 13.65% |
| K13-c1r | busy | StableApify | 13.52% / 22.28% | 6.78% / 7.03% |
| K13-c1r | busy | CoinStats(0.01 or less) | 206.84% / 353.21% | 95.61% / 101.66% |
| K13-c1r | busy | Exa(0.001 or less) | 508.43% / 1114.67% | 173.81% / 253.64% |
| K13-c1r | busy | BlockRun | 42.00% / 42.06% | 41.99% / 42.03% |
| K13-c1r | busy | StableEnrich(Out candidates excluded) | 2.99% / 4.21% | 2.49% / 2.76% |
| K13-c1r | busy | T01t pooled | 3.76% / 5.76% | 2.91% / 3.31% |
| K13-c1r | median | median seller | 32.46% / 55.94% | 16.37% / 18.09% |
| K13-c1r | median | StableApify | 35.15% / 60.98% | 15.32% / 16.16% |
| K13-c1r | median | CoinStats(0.01 or less) | 337.11% / 577.09% | 156.86% / 169.44% |
| K13-c1r | median | Exa(0.001 or less) | 492.31% / 1106.74% | 164.98% / 251.75% |
| K13-c1r | median | BlockRun | 33.59% / 33.64% | 33.59% / 33.61% |
| K13-c1r | median | StableEnrich(Out candidates excluded) | 3.06% / 4.73% | 2.38% / 2.74% |
| K13-c1r | median | T01t pooled | 4.53% / 7.07% | 3.45% / 3.97% |
| K13-c1r | quiet | median seller | 50.16% / 88.10% | 21.09% / 22.36% |
| K13-c1r | quiet | StableApify | 50.37% / 88.20% | 21.69% / 23.34% |
| K13-c1r | quiet | CoinStats(0.01 or less) | 269.62% / 452.78% | 144.48% / 169.79% |
| K13-c1r | quiet | Exa(0.001 or less) | 574.73% / 1334.41% | 182.87% / 296.76% |
| K13-c1r | quiet | BlockRun | 2.50% / 2.90% | 2.34% / 2.44% |
| K13-c1r | quiet | StableEnrich(Out candidates excluded) | 3.62% / 5.15% | 2.99% / 3.31% |
| K13-c1r | quiet | T01t pooled | 4.54% / 6.81% | 3.56% / 4.02% |

## 5. auxiliary calculation (for verdicts not used not)


### 5.1 anchor cells only changed(d_prf = d_cur = 0, difference transplant)


### median seller(lower / upper) and 10% within seller count(seven among, lower / upper)

| calculation | N | busy | median | quiet | 10% within count lower(busy, median, quiet) | upper |
|---|---|---|---|---|---|---|
| c1 anchor only | 1 | 16.85% / 30.47% | 31.88% / 55.35% | 49.23% / 87.17% | 1, 1, 2 | 1, 1, 2 |
| c1 anchor only | 4 | 12.28% / 17.53% | 19.05% / 24.89% | 27.20% / 37.20% | 3, 1, 2 | 1, 1, 2 |
| c1 anchor only | 16 | 11.16% / 14.26% | 16.63% / 19.18% | 21.57% / 24.59% | 3, 1, 2 | 2, 1, 2 |
| c1 anchor only | 64 | 10.92% / 13.45% | 16.04% / 17.76% | 20.16% / 21.43% | 3, 1, 2 | 2, 1, 2 |
| c1r anchor only | 1 | 16.79% / 30.41% | 31.88% / 55.35% | 49.23% / 87.17% | 1, 1, 2 | 1, 1, 2 |
| c1r anchor only | 4 | 12.23% / 17.47% | 18.95% / 24.79% | 27.20% / 37.20% | 3, 1, 2 | 1, 1, 2 |
| c1r anchor only | 16 | 11.10% / 14.21% | 16.54% / 19.08% | 21.57% / 24.59% | 3, 1, 2 | 2, 1, 2 |
| c1r anchor only | 64 | 10.86% / 13.40% | 15.94% / 17.66% | 20.16% / 21.43% | 3, 1, 2 | 2, 1, 2 |

### target seller and set (lower / upper, N = 1 and 64)

| calculation | window | target | N 1 | N 64 |
|---|---|---|---|---|
| c1 anchor only | busy | median seller | 16.85% / 30.47% | 10.92% / 13.45% |
| c1 anchor only | busy | StableApify | 13.29% / 22.05% | 6.55% / 6.80% |
| c1 anchor only | busy | CoinStats(0.01 or less) | 203.36% / 349.73% | 92.12% / 98.18% |
| c1 anchor only | busy | Exa(0.001 or less) | 496.56% / 1102.80% | 161.95% / 241.77% |
| c1 anchor only | busy | BlockRun | 41.98% / 42.03% | 41.97% / 42.01% |
| c1 anchor only | busy | StableEnrich(Out candidates excluded) | 2.97% / 4.19% | 2.47% / 2.73% |
| c1 anchor only | busy | T01t pooled | 3.73% / 5.72% | 2.87% / 3.28% |
| c1 anchor only | median | median seller | 31.88% / 55.35% | 16.04% / 17.76% |
| c1 anchor only | median | StableApify | 34.51% / 60.34% | 14.68% / 15.52% |
| c1 anchor only | median | CoinStats(0.01 or less) | 331.48% / 571.46% | 151.23% / 163.81% |
| c1 anchor only | median | Exa(0.001 or less) | 480.53% / 1094.96% | 153.20% / 239.97% |
| c1 anchor only | median | BlockRun | 33.58% / 33.62% | 33.57% / 33.60% |
| c1 anchor only | median | StableEnrich(Out candidates excluded) | 3.04% / 4.70% | 2.36% / 2.71% |
| c1 anchor only | median | T01t pooled | 4.50% / 7.04% | 3.42% / 3.94% |
| c1 anchor only | quiet | median seller | 49.23% / 87.17% | 20.16% / 21.43% |
| c1 anchor only | quiet | StableApify | 49.45% / 87.28% | 20.78% / 22.43% |
| c1 anchor only | quiet | CoinStats(0.01 or less) | 265.70% / 448.87% | 140.57% / 165.87% |
| c1 anchor only | quiet | Exa(0.001 or less) | 560.43% / 1320.11% | 168.57% / 282.46% |
| c1 anchor only | quiet | BlockRun | 2.48% / 2.88% | 2.32% / 2.42% |
| c1 anchor only | quiet | StableEnrich(Out candidates excluded) | 3.60% / 5.13% | 2.97% / 3.29% |
| c1 anchor only | quiet | T01t pooled | 4.52% / 6.78% | 3.54% / 4.00% |
| c1r anchor only | busy | median seller | 16.79% / 30.41% | 10.86% / 13.40% |
| c1r anchor only | busy | StableApify | 13.29% / 22.05% | 6.55% / 6.80% |
| c1r anchor only | busy | CoinStats(0.01 or less) | 203.36% / 349.73% | 92.12% / 98.18% |
| c1r anchor only | busy | Exa(0.001 or less) | 496.56% / 1102.80% | 161.95% / 241.77% |
| c1r anchor only | busy | BlockRun | 41.98% / 42.03% | 41.97% / 42.01% |
| c1r anchor only | busy | StableEnrich(Out candidates excluded) | 2.95% / 4.17% | 2.45% / 2.71% |
| c1r anchor only | busy | T01t pooled | 3.71% / 5.70% | 2.85% / 3.25% |
| c1r anchor only | median | median seller | 31.88% / 55.35% | 15.94% / 17.66% |
| c1r anchor only | median | StableApify | 34.51% / 60.34% | 14.68% / 15.52% |
| c1r anchor only | median | CoinStats(0.01 or less) | 331.48% / 571.46% | 151.23% / 163.81% |
| c1r anchor only | median | Exa(0.001 or less) | 480.53% / 1094.96% | 153.20% / 239.97% |
| c1r anchor only | median | BlockRun | 33.58% / 33.62% | 33.57% / 33.60% |
| c1r anchor only | median | StableEnrich(Out candidates excluded) | 3.01% / 4.68% | 2.33% / 2.69% |
| c1r anchor only | median | T01t pooled | 4.46% / 7.01% | 3.38% / 3.90% |
| c1r anchor only | quiet | median seller | 49.23% / 87.17% | 20.16% / 21.43% |
| c1r anchor only | quiet | StableApify | 49.45% / 87.28% | 20.78% / 22.43% |
| c1r anchor only | quiet | CoinStats(0.01 or less) | 265.70% / 448.87% | 140.57% / 165.87% |
| c1r anchor only | quiet | Exa(0.001 or less) | 560.43% / 1320.11% | 168.57% / 282.46% |
| c1r anchor only | quiet | BlockRun | 2.47% / 2.87% | 2.32% / 2.41% |
| c1r anchor only | quiet | StableEnrich(Out candidates excluded) | 3.57% / 5.10% | 2.94% / 3.26% |
| c1r anchor only | quiet | T01t pooled | 4.48% / 6.74% | 3.50% / 3.96% |

### 5.2 absolute values(measured cell as is)


### median seller(lower / upper) and 10% within seller count(seven among, lower / upper)

| calculation | N | busy | median | quiet | 10% within count lower(busy, median, quiet) | upper |
|---|---|---|---|---|---|---|
| absolute base | 1 | 30.76% / 44.38% | 59.48% / 82.95% | 92.19% / 130.13% | 1, 1, 2 | 1, 1, 2 |
| absolute base | 4 | 26.20% / 31.44% | 45.78% / 51.88% | 70.16% / 80.16% | 1, 1, 2 | 1, 1, 2 |
| absolute base | 16 | 25.02% / 28.18% | 42.28% / 44.04% | 64.53% / 67.55% | 1, 1, 2 | 1, 1, 2 |
| absolute base | 64 | 24.75% / 27.38% | 41.42% / 42.09% | 63.14% / 64.41% | 1, 1, 2 | 1, 1, 2 |
| absolute c1 | 1 | 22.66% / 36.28% | 40.03% / 63.50% | 60.90% / 98.84% | 1, 1, 2 | 1, 1, 2 |
| absolute c1 | 4 | 18.09% / 23.34% | 27.02% / 32.86% | 38.87% / 48.87% | 1, 1, 2 | 1, 1, 2 |
| absolute c1 | 16 | 16.92% / 20.07% | 24.61% / 27.15% | 33.24% / 36.25% | 1, 1, 2 | 1, 1, 2 |
| absolute c1 | 64 | 16.64% / 19.27% | 24.01% / 25.74% | 31.83% / 33.10% | 1, 1, 2 | 1, 1, 2 |
| absolute c1r | 1 | 22.56% / 36.17% | 39.77% / 63.24% | 60.48% / 98.42% | 1, 1, 2 | 1, 1, 2 |
| absolute c1r | 4 | 17.99% / 23.24% | 26.83% / 32.68% | 38.45% / 48.45% | 1, 1, 2 | 1, 1, 2 |
| absolute c1r | 16 | 16.82% / 19.97% | 24.42% / 26.97% | 32.82% / 35.83% | 1, 1, 2 | 1, 1, 2 |
| absolute c1r | 64 | 16.53% / 19.16% | 23.83% / 25.55% | 31.41% / 32.68% | 1, 1, 2 | 1, 1, 2 |

### target seller and set (lower / upper, N = 1 and 64)

| calculation | window | target | N 1 | N 64 |
|---|---|---|---|---|
| absolute base | busy | median seller | 30.76% / 44.38% | 24.75% / 27.38% |
| absolute base | busy | StableApify | 24.51% / 33.27% | 17.78% / 18.04% |
| absolute base | busy | CoinStats(0.01 or less) | 376.61% / 522.98% | 265.48% / 271.53% |
| absolute base | busy | Exa(0.001 or less) | 1047.76% / 1654.00% | 713.37% / 793.20% |
| absolute base | busy | BlockRun | 43.21% / 43.26% | 43.20% / 43.24% |
| absolute base | busy | StableEnrich(Out candidates excluded) | 4.38% / 5.60% | 3.89% / 4.15% |
| absolute base | busy | T01t pooled | 5.90% / 7.90% | 5.05% / 5.45% |
| absolute base | median | median seller | 59.48% / 82.95% | 41.42% / 42.09% |
| absolute base | median | StableApify | 64.28% / 90.12% | 44.47% / 45.30% |
| absolute base | median | CoinStats(0.01 or less) | 608.96% / 848.93% | 428.86% / 441.45% |
| absolute base | median | Exa(0.001 or less) | 1028.08% / 1642.51% | 700.98% / 787.75% |
| absolute base | median | BlockRun | 33.93% / 33.97% | 33.92% / 33.95% |
| absolute base | median | StableEnrich(Out candidates excluded) | 4.88% / 6.54% | 4.20% / 4.55% |
| absolute base | median | T01t pooled | 7.35% / 9.89% | 6.27% / 6.80% |
| absolute base | quiet | median seller | 92.19% / 130.13% | 63.14% / 64.41% |
| absolute base | quiet | StableApify | 92.01% / 129.83% | 63.35% / 65.00% |
| absolute base | quiet | CoinStats(0.01 or less) | 467.92% / 651.08% | 342.92% / 368.22% |
| absolute base | quiet | Exa(0.001 or less) | 1218.26% / 1977.94% | 826.66% / 940.55% |
| absolute base | quiet | BlockRun | 2.95% / 3.35% | 2.79% / 2.89% |
| absolute base | quiet | StableEnrich(Out candidates excluded) | 5.48% / 7.01% | 4.85% / 5.18% |
| absolute base | quiet | T01t pooled | 7.17% / 9.43% | 6.19% / 6.65% |
| absolute c1 | busy | median seller | 22.66% / 36.28% | 16.64% / 19.27% |
| absolute c1 | busy | StableApify | 17.27% / 26.02% | 10.52% / 10.78% |
| absolute c1 | busy | CoinStats(0.01 or less) | 256.81% / 403.18% | 145.58% / 151.63% |
| absolute c1 | busy | Exa(0.001 or less) | 637.79% / 1244.03% | 303.17% / 383.00% |
| absolute c1 | busy | BlockRun | 43.16% / 43.21% | 43.15% / 43.19% |
| absolute c1 | busy | StableEnrich(Out candidates excluded) | 3.70% / 4.92% | 3.21% / 3.47% |
| absolute c1 | busy | T01t pooled | 4.75% / 6.74% | 3.89% / 4.29% |
| absolute c1 | median | median seller | 40.03% / 63.50% | 24.01% / 25.74% |
| absolute c1 | median | StableApify | 42.95% / 68.78% | 23.12% / 23.96% |
| absolute c1 | median | CoinStats(0.01 or less) | 414.82% / 654.79% | 234.56% / 247.14% |
| absolute c1 | median | Exa(0.001 or less) | 620.98% / 1235.42% | 293.66% / 380.42% |
| absolute c1 | median | BlockRun | 33.92% / 33.96% | 33.91% / 33.94% |
| absolute c1 | median | StableEnrich(Out candidates excluded) | 3.94% / 5.60% | 3.26% / 3.61% |
| absolute c1 | median | T01t pooled | 5.88% / 8.43% | 4.80% / 5.33% |
| absolute c1 | quiet | median seller | 60.90% / 98.84% | 31.83% / 33.10% |
| absolute c1 | quiet | StableApify | 61.14% / 98.96% | 32.46% / 34.11% |
| absolute c1 | quiet | CoinStats(0.01 or less) | 333.12% / 516.28% | 207.98% / 233.28% |
| absolute c1 | quiet | Exa(0.001 or less) | 724.22% / 1483.90% | 332.36% / 446.25% |
| absolute c1 | quiet | BlockRun | 2.74% / 3.14% | 2.58% / 2.68% |
| absolute c1 | quiet | StableEnrich(Out candidates excluded) | 4.60% / 6.13% | 3.97% / 4.29% |
| absolute c1 | quiet | T01t pooled | 5.84% / 8.10% | 4.86% / 5.32% |
| absolute c1r | busy | median seller | 22.56% / 36.17% | 16.53% / 19.16% |
| absolute c1r | busy | StableApify | 17.17% / 25.93% | 10.43% / 10.69% |
| absolute c1r | busy | CoinStats(0.01 or less) | 255.18% / 401.55% | 143.95% / 150.00% |
| absolute c1r | busy | Exa(0.001 or less) | 632.19% / 1238.43% | 297.57% / 377.40% |
| absolute c1r | busy | BlockRun | 43.17% / 43.22% | 43.16% / 43.19% |
| absolute c1r | busy | StableEnrich(Out candidates excluded) | 3.70% / 4.92% | 3.20% / 3.47% |
| absolute c1r | busy | T01t pooled | 4.74% / 6.73% | 3.88% / 4.29% |
| absolute c1r | median | median seller | 39.77% / 63.24% | 23.83% / 25.55% |
| absolute c1r | median | StableApify | 42.66% / 68.50% | 22.84% / 23.67% |
| absolute c1r | median | CoinStats(0.01 or less) | 412.17% / 652.15% | 231.91% / 244.50% |
| absolute c1r | median | Exa(0.001 or less) | 615.42% / 1229.86% | 288.09% / 374.86% |
| absolute c1r | median | BlockRun | 33.92% / 33.97% | 33.92% / 33.94% |
| absolute c1r | median | StableEnrich(Out candidates excluded) | 3.93% / 5.60% | 3.25% / 3.61% |
| absolute c1r | median | T01t pooled | 5.87% / 8.42% | 4.79% / 5.32% |
| absolute c1r | quiet | median seller | 60.48% / 98.42% | 31.41% / 32.68% |
| absolute c1r | quiet | StableApify | 60.72% / 98.55% | 32.05% / 33.70% |
| absolute c1r | quiet | CoinStats(0.01 or less) | 331.28% / 514.45% | 206.15% / 231.45% |
| absolute c1r | quiet | Exa(0.001 or less) | 717.46% / 1477.14% | 325.61% / 439.50% |
| absolute c1r | quiet | BlockRun | 2.74% / 3.14% | 2.59% / 2.69% |
| absolute c1r | quiet | StableEnrich(Out candidates excluded) | 4.59% / 6.12% | 3.96% / 4.29% |
| absolute c1r | quiet | T01t pooled | 5.83% / 8.09% | 4.85% / 5.31% |

### 5.3 scenario M: bundle row absent not computed not


## 6. text verdict

| verdict | value | threshold | holds |
|---|---|---|---|
| JK13a | 0.013979134403300302 | 0.6 | holds |
| JK13a-r | -0.013621073815430993 | 0.5 | holds |
| JK13b | {'busy': 0.1101798094581607, 'median': 0.16253909238236292, 'quiet': 0.20629688274687524} | 0.2 | does not hold not |
| JK13b-r | {'busy': 0.11051009902311927, 'median': 0.1636880932230035, 'quiet': 0.21090909631034893} | 0.2 | does not hold not |
| JK13c | {'busy': 3, 'median': 1, 'quiet': 2} | {'busy': 1, 'median': 1, 'quiet': 2} | holds |
| JK13c-r | {'busy': 3, 'median': 1, 'quiet': 2} | {'busy': 1, 'median': 1, 'quiet': 2} | holds |
| JK13d | {'prove': 5953, 'release_one': 2965, 'dispute_open': 4403, 'double_sign': 3519, 'swap_proof': 2849} | 5000 | does not hold not |
| JK13d-r | {'prove': 9278, 'release_one': 5944, 'dispute_open': 7728, 'double_sign': 8185, 'swap_proof': 8076} | 5000 | does not hold not |
