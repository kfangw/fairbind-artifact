# K13 prior prediction(hand estimate, for verdicts not used not; k13_cost.py --hand)

F_bundled-anchor_feasibility.md 5.3 estimate this with the wrapper again computed is. anchor fixed gas C1 110,500, C1r 127,600 removed proof and cursor restored gas 0 kept.

k12.py SHA-256 9eda92027042ee43e3eafd402192d1883100be5bdce900def9be0584785abcc1


### median seller(lower / upper) and 10% within seller count(seven among, lower / upper)

| calculation | N | busy | median | quiet | 10% within count lower(busy, median, quiet) | upper |
|---|---|---|---|---|---|---|
| K12(G11) | 1 | 24.18% / 37.80% | 47.45% / 70.92% | 73.40% / 111.34% | 1, 1, 2 | 1, 1, 2 |
| K12(G11) | 4 | 19.61% / 24.86% | 33.75% / 39.85% | 51.37% / 61.37% | 1, 1, 2 | 1, 1, 2 |
| K12(G11) | 16 | 18.44% / 21.59% | 30.25% / 32.01% | 45.74% / 48.75% | 1, 1, 2 | 1, 1, 2 |
| K12(G11) | 64 | 18.15% / 20.79% | 29.37% / 30.04% | 44.33% / 45.60% | 1, 1, 2 | 1, 1, 2 |
| estimate C1 | 1 | 19.82% / 33.44% | 36.99% / 60.47% | 56.59% / 94.53% | 1, 1, 2 | 1, 1, 2 |
| estimate C1 | 4 | 15.26% / 20.51% | 23.38% / 29.40% | 34.56% / 44.56% | 1, 1, 2 | 1, 1, 2 |
| estimate C1 | 16 | 14.08% / 17.24% | 20.97% / 23.52% | 28.93% / 31.94% | 2, 1, 2 | 1, 1, 2 |
| estimate C1 | 64 | 13.80% / 16.43% | 20.37% / 22.10% | 27.52% / 28.79% | 2, 1, 2 | 2, 1, 2 |
| estimate C1r | 1 | 19.15% / 32.77% | 35.37% / 58.85% | 53.99% / 91.93% | 1, 1, 2 | 1, 1, 2 |
| estimate C1r | 4 | 14.58% / 19.83% | 22.20% / 28.05% | 31.96% / 41.96% | 1, 1, 2 | 1, 1, 2 |
| estimate C1r | 16 | 13.41% / 16.57% | 19.79% / 22.34% | 26.32% / 29.34% | 3, 1, 2 | 2, 1, 2 |
| estimate C1r | 64 | 13.13% / 15.76% | 19.19% / 20.92% | 24.92% / 26.19% | 3, 1, 2 | 2, 1, 2 |

### target seller and set (lower / upper, N = 1 and 64)

| calculation | window | target | N 1 | N 64 |
|---|---|---|---|---|
| K12(G11) | busy | median seller | 24.18% / 37.80% | 18.15% / 20.79% |
| K12(G11) | busy | StableApify | 19.66% / 28.42% | 12.92% / 13.17% |
| K12(G11) | busy | CoinStats(0.01 or less) | 301.21% / 447.59% | 189.98% / 196.03% |
| K12(G11) | busy | Exa(0.001 or less) | 806.14% / 1412.38% | 471.53% / 551.35% |
| K12(G11) | busy | BlockRun | 42.05% / 42.10% | 42.04% / 42.07% |
| K12(G11) | busy | StableEnrich(Out candidates excluded) | 3.67% / 4.89% | 3.17% / 3.44% |
| K12(G11) | busy | T01t pooled | 4.84% / 6.84% | 3.99% / 4.39% |
| K12(G11) | median | median seller | 47.45% / 70.92% | 29.37% / 30.04% |
| K12(G11) | median | StableApify | 51.28% / 77.11% | 31.45% / 32.29% |
| K12(G11) | median | CoinStats(0.01 or less) | 488.07% / 728.04% | 307.81% / 320.40% |
| K12(G11) | median | Exa(0.001 or less) | 788.07% / 1402.50% | 460.74% / 547.51% |
| K12(G11) | median | BlockRun | 33.60% / 33.64% | 33.59% / 33.62% |
| K12(G11) | median | StableEnrich(Out candidates excluded) | 4.00% / 5.67% | 3.33% / 3.68% |
| K12(G11) | median | T01t pooled | 5.97% / 8.51% | 4.89% / 5.41% |
| K12(G11) | quiet | median seller | 73.40% / 111.34% | 44.33% / 45.60% |
| K12(G11) | quiet | StableApify | 73.40% / 111.23% | 44.72% / 46.37% |
| K12(G11) | quiet | CoinStats(0.01 or less) | 380.22% / 563.38% | 255.09% / 280.39% |
| K12(G11) | quiet | Exa(0.001 or less) | 929.62% / 1689.30% | 537.76% / 651.65% |
| K12(G11) | quiet | BlockRun | 2.70% / 3.10% | 2.54% / 2.64% |
| K12(G11) | quiet | StableEnrich(Out candidates excluded) | 4.51% / 6.04% | 3.88% / 4.20% |
| K12(G11) | quiet | T01t pooled | 5.84% / 8.10% | 4.86% / 5.32% |
| estimate C1 | busy | median seller | 19.82% / 33.44% | 13.80% / 16.43% |
| estimate C1 | busy | StableApify | 15.76% / 24.52% | 9.02% / 9.27% |
| estimate C1 | busy | CoinStats(0.01 or less) | 236.88% / 383.26% | 125.65% / 131.71% |
| estimate C1 | busy | Exa(0.001 or less) | 585.95% / 1192.19% | 251.34% / 331.16% |
| estimate C1 | busy | BlockRun | 42.02% / 42.07% | 42.01% / 42.04% |
| estimate C1 | busy | StableEnrich(Out candidates excluded) | 3.30% / 4.52% | 2.80% / 3.07% |
| estimate C1 | busy | T01t pooled | 4.22% / 6.21% | 3.36% / 3.76% |
| estimate C1 | median | median seller | 36.99% / 60.47% | 20.37% / 22.10% |
| estimate C1 | median | StableApify | 39.81% / 65.65% | 19.99% / 20.82% |
| estimate C1 | median | CoinStats(0.01 or less) | 383.82% / 623.80% | 203.56% / 216.15% |
| estimate C1 | median | Exa(0.001 or less) | 569.42% / 1183.86% | 242.10% / 328.86% |
| estimate C1 | median | BlockRun | 33.59% / 33.63% | 33.58% / 33.61% |
| estimate C1 | median | StableEnrich(Out candidates excluded) | 3.50% / 5.16% | 2.82% / 3.17% |
| estimate C1 | median | T01t pooled | 5.18% / 7.72% | 4.10% / 4.62% |
| estimate C1 | quiet | median seller | 56.59% / 94.53% | 27.52% / 28.79% |
| estimate C1 | quiet | StableApify | 56.81% / 94.64% | 28.14% / 29.79% |
| estimate C1 | quiet | CoinStats(0.01 or less) | 307.85% / 491.01% | 182.71% / 208.02% |
| estimate C1 | quiet | Exa(0.001 or less) | 664.26% / 1423.94% | 272.40% / 386.29% |
| estimate C1 | quiet | BlockRun | 2.58% / 2.98% | 2.43% / 2.52% |
| estimate C1 | quiet | StableEnrich(Out candidates excluded) | 4.03% / 5.56% | 3.40% / 3.72% |
| estimate C1 | quiet | T01t pooled | 5.12% / 7.38% | 4.14% / 4.60% |
| estimate C1r | busy | median seller | 19.15% / 32.77% | 13.13% / 15.76% |
| estimate C1r | busy | StableApify | 15.16% / 23.91% | 8.42% / 8.67% |
| estimate C1r | busy | CoinStats(0.01 or less) | 226.93% / 373.30% | 115.69% / 121.75% |
| estimate C1r | busy | Exa(0.001 or less) | 551.88% / 1158.12% | 217.26% / 297.09% |
| estimate C1r | busy | BlockRun | 42.01% / 42.07% | 42.00% / 42.04% |
| estimate C1r | busy | StableEnrich(Out candidates excluded) | 3.24% / 4.46% | 2.74% / 3.01% |
| estimate C1r | busy | T01t pooled | 4.12% / 6.12% | 3.26% / 3.67% |
| estimate C1r | median | median seller | 35.37% / 58.85% | 19.19% / 20.92% |
| estimate C1r | median | StableApify | 38.04% / 63.88% | 18.22% / 19.05% |
| estimate C1r | median | CoinStats(0.01 or less) | 367.69% / 607.66% | 187.43% / 200.01% |
| estimate C1r | median | Exa(0.001 or less) | 535.59% / 1150.02% | 208.26% / 295.03% |
| estimate C1r | median | BlockRun | 33.59% / 33.63% | 33.58% / 33.61% |
| estimate C1r | median | StableEnrich(Out candidates excluded) | 3.42% / 5.08% | 2.74% / 3.09% |
| estimate C1r | median | T01t pooled | 5.05% / 7.60% | 3.97% / 4.50% |
| estimate C1r | quiet | median seller | 53.99% / 91.93% | 24.92% / 26.19% |
| estimate C1r | quiet | StableApify | 54.25% / 92.08% | 25.57% / 27.22% |
| estimate C1r | quiet | CoinStats(0.01 or less) | 296.65% / 479.81% | 171.51% / 196.82% |
| estimate C1r | quiet | Exa(0.001 or less) | 623.19% / 1382.88% | 231.34% / 345.23% |
| estimate C1r | quiet | BlockRun | 2.56% / 2.96% | 2.41% / 2.51% |
| estimate C1r | quiet | StableEnrich(Out candidates excluded) | 3.95% / 5.48% | 3.32% / 3.65% |
| estimate C1r | quiet | T01t pooled | 5.01% / 7.27% | 4.03% / 4.49% |
