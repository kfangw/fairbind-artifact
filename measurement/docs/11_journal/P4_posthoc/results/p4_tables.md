**all values post hoc calculations registered verdict none.** `p4.py` output. mode N, σ 1, r 10%, a 0, w 0.00173, per seller optimal k. costs revenue relative to %.

k11b_output.md reproduction: True. Table 4 cell match: True. multiple 1 reproduction max difference: FI(P3) 1.1e-16, FR(K14) 0.0e+00, reference B(P3 (b) and FI-b) 1.1e-16.

## 1. sketch constant (reference A value)

| constant | kind | k11b.py lines | value | source |
|---|---|---|---|---|
| REL_F | gas | 185 | {'pool': 105742, 'ledger': 114624} | G10c 3.3 release fixed part (sketch) |
| REL_M | gas | 184 | 2930 | G10c 3.3 release per sale (sketch) |
| REL_K | gas | 184 | 2083 | G10c 3.3 release per closed case (sketch) |
| RW_F | wei | 189-190 | 945606403.8666666 | G10c release rows, L1 wei fixed part (sketch) |
| RW_M | wei | 189 | 245940057.89166668 | G10c release rows, L1 wei per sale (sketch) |
| L1W_F | wei | 166-169, 707 | {0: 1786605677.666666, 1: 1870582712.0} | G10b anchor rows, L1 wei fixed part (sketch; G11 L1 only in sensitivity L) |
| L1W_M | wei | 166-168, 707 | {0: 1150843806.1666667, 1: 1566632536.125} | G10b anchor rows, L1 wei per sale (sketch) |
| W_REQ | wei | 179, 708 | 734567965 | G10c sample request L1 wei (sketch) |
| W_VRF | wei | 181, 708 | 2593604493 | G10c VRF acceptance L1 wei (sketch) |
| CPG.TEE.gas | gas | 170-172 | 36440 | G10-1 enclave receipt (sketch; no G11 row) |
| CPG.TEE.wei | wei | 170-172 | 2157333560 | G10-1 enclave receipt L1 wei (sketch) |
| CPG.RS3.wei | wei | 704 | 2132754915 | G10b RedStone row L1 wei kept under the measured tier-1a gas (sketch) |
| CPG.SP0.wei | wei | 704 | 28173828378 | G10b storage-proof row L1 wei kept under the measured tier-0 gas (sketch) |
| G_BH_READ | gas | 140 | 5000 | tier-0 block-hash history read (estimate) |
| SP0_UP.ext | gas | 232-233, 705 | 119904.0 | upper tier-0: 4 account nodes x G10b node gas (sketch extrapolation) |
| SETTLE | gas | 174-176 | {'ledger': {'first': 78617, 'later': 61543}, 'pool': {'first': 89807, 'later': 72733}} | G10c-1 settle minus x402 (sketch) |
| G_FAIL | gas | 225-230 | 104276 | failure path 21,000 + 18,536 + 64,740 (sketch) |
| CL_BILL | gas | 207-214 | 157644 | Chainlink fulfillment billed gas + new slot (sketch) |
| CL_L1_CHARGED | wei | 210 | 4321371668 | Chainlink fulfillment L1 charge (sketch) |
| G_DET | gas | 223-224 | 5200 | upper allowance: determinism check (estimate) |
| G_LVL | gas | 222 | 900 | upper allowance: gas per Merkle level (estimate) |

# reference A: K11b as is(Table 4, per sale release 2,930 sketch)

linear check(multiple 2, constant all): max relative difference 3.8e-16, release capacity unit changed cell 126 / 756.

## 2. per term share (revenue relative to %, chosen k; each cell term whole / its among sketch value share)


### six seller sum, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.23 / 0.00 | 0.29 / 0.00 | 0.29 / 0.00 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.31 / 0.31 | 0.41 / 0.41 | 0.44 / 0.44 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 4.84 / 0.33 | 5.97 / 0.43 | 5.84 / 0.46 |

### six seller sum, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.24 / 0.01 | 0.31 / 0.02 | 0.31 / 0.02 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 2.11 / 1.43 | 2.67 / 1.82 | 2.39 / 1.63 |
| release | sketch(reference B: per sale share only measured) | 0.89 / 0.89 | 1.14 / 1.14 | 1.07 / 1.07 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| detincl | estimated margin | 0.03 / 0.03 | 0.03 / 0.03 | 0.03 / 0.03 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 6.84 / 2.38 | 8.51 / 3.04 | 8.10 / 2.78 |

### six seller sum, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.23 / 0.00 | 0.29 / 0.00 | 0.29 / 0.00 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.31 / 0.31 | 0.41 / 0.41 | 0.44 / 0.44 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| facil | sketch | 4.94 / 4.94 | 6.75 / 6.75 | 7.04 / 7.04 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 9.79 / 5.28 | 12.72 / 7.18 | 12.88 / 7.51 |

### six seller sum, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.15 / 0.00 | 1.36 / 0.01 | 1.38 / 0.01 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.33 / 0.33 | 0.42 / 0.42 | 0.46 / 0.46 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 8.05 / 0.36 | 8.59 / 0.46 | 8.39 / 0.49 |

### six seller sum, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.18 / 0.03 | 1.46 / 0.10 | 1.47 / 0.10 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 2.11 / 1.43 | 2.67 / 1.82 | 2.39 / 1.63 |
| release | sketch(reference B: per sale share only measured) | 0.90 / 0.90 | 1.16 / 1.16 | 1.09 / 1.09 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| detincl | estimated margin | 0.17 / 0.17 | 0.15 / 0.15 | 0.16 / 0.16 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| total | | 10.20 / 2.56 | 11.34 / 3.26 | 10.85 / 3.00 |

### six seller sum, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.15 / 0.00 | 1.36 / 0.01 | 1.38 / 0.01 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.33 / 0.33 | 0.42 / 0.42 | 0.46 / 0.46 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| facil | sketch | 4.94 / 4.94 | 6.75 / 6.75 | 7.04 / 7.04 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 12.99 / 5.30 | 15.35 / 7.21 | 15.43 / 7.53 |

### StableEnrich, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.21 / 0.21 | 0.22 / 0.22 | 0.30 / 0.30 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 3.67 / 0.22 | 4.00 / 0.24 | 4.51 / 0.32 |

### StableEnrich, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 1.25 / 0.85 | 1.72 / 1.17 | 1.58 / 1.07 |
| release | sketch(reference B: per sale share only measured) | 0.58 / 0.58 | 0.73 / 0.73 | 0.76 / 0.76 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| detincl | estimated margin | 0.03 / 0.03 | 0.03 / 0.03 | 0.03 / 0.03 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| total | | 4.89 / 1.48 | 5.67 / 1.94 | 6.04 / 1.89 |

### StableEnrich, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.21 / 0.21 | 0.22 / 0.22 | 0.30 / 0.30 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| facil | sketch | 3.94 / 3.94 | 4.15 / 4.15 | 5.74 / 5.74 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 7.62 / 4.17 | 8.15 / 4.38 | 10.25 / 6.06 |

### StableEnrich, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.23 / 0.23 | 0.24 / 0.24 | 0.32 / 0.32 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 6.89 / 0.24 | 6.39 / 0.26 | 6.82 / 0.34 |

### StableEnrich, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 1.25 / 0.85 | 1.72 / 1.17 | 1.58 / 1.07 |
| release | sketch(reference B: per sale share only measured) | 0.60 / 0.60 | 0.74 / 0.74 | 0.78 / 0.78 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| detincl | estimated margin | 0.17 / 0.17 | 0.15 / 0.15 | 0.16 / 0.16 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| total | | 8.25 / 1.63 | 8.17 / 2.08 | 8.48 / 2.03 |

### StableEnrich, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.23 / 0.23 | 0.24 / 0.24 | 0.32 / 0.32 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| facil | sketch | 3.94 / 3.94 | 4.15 / 4.15 | 5.74 / 5.74 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 10.83 / 4.19 | 10.54 / 4.40 | 12.57 / 6.08 |

### BlockRun, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.66 / 0.66 | 0.19 / 0.19 | 0.08 / 0.08 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 42.05 / 0.78 | 33.60 / 0.26 | 2.70 / 0.17 |

### BlockRun, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.03 / 0.02 | 0.02 / 0.01 | 0.39 / 0.27 |
| release | sketch(reference B: per sale share only measured) | 0.66 / 0.66 | 0.19 / 0.19 | 0.20 / 0.20 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| detincl | estimated margin | 0.03 / 0.03 | 0.02 / 0.02 | 0.03 / 0.03 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| total | | 42.10 / 0.84 | 33.64 / 0.30 | 3.10 / 0.58 |

### BlockRun, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.66 / 0.66 | 0.19 / 0.19 | 0.08 / 0.08 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| facil | sketch | 13.55 / 13.55 | 3.84 / 3.84 | 1.51 / 1.51 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 55.60 / 14.33 | 37.44 / 4.10 | 4.21 / 1.68 |

### BlockRun, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.68 / 0.68 | 0.20 / 0.20 | 0.09 / 0.09 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 95.13 / 1.14 | 78.11 / 0.44 | 4.71 / 0.28 |

### BlockRun, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.03 / 0.02 | 0.02 / 0.01 | 0.39 / 0.27 |
| release | sketch(reference B: per sale share only measured) | 0.68 / 0.68 | 0.20 / 0.20 | 0.20 / 0.20 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| detincl | estimated margin | 0.17 / 0.17 | 0.09 / 0.09 | 0.07 / 0.07 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| total | | 95.32 / 1.33 | 78.22 / 0.55 | 5.15 / 0.73 |

### BlockRun, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 0.68 / 0.68 | 0.20 / 0.20 | 0.09 / 0.09 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| facil | sketch | 13.55 / 13.55 | 3.84 / 3.84 | 1.51 / 1.51 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 108.68 / 14.69 | 81.95 / 4.28 | 6.23 / 1.79 |

## 3. multiple grid (window: busy / median / quiet; *  10% over)

| method | k | sum V1 lower | sum V1 upper | sum V1 facil | sum V0.2 lower | sum V0.2 upper | 10% within seller(V1 lower) | StableEnrich V1 lower | BlockRun V1 lower | FI sum V1 lower | FR main sum V1 lower | w* V1 lower |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constant all(gas and L1 wei) | 1 | 4.84 / 5.97 / 5.84 | 6.84 / 8.51 / 8.10 | 9.79 / 12.72* / 12.88* | 8.05 / 8.59 / 8.39 | 10.20* / 11.34* / 10.85* | 1/6 / 1/6 / 1/6 | 3.67 / 4.00 / 4.51 | 42.05 / 33.60 / 2.70 | 13.42 / 33.90 / 24.16 | 12.22 / 12.74 / 16.29 | 0.0136 / 0.013 / 0.0143 |
| constant all(gas and L1 wei) | 1.5 | 5.01 / 6.19 / 6.07 | 8.03 / 10.03* / 9.49 | 12.43* / 16.31* / 16.64* | 8.22 / 8.82 / 8.64 | 11.48* / 12.97* / 12.35* | 1/6 / 1/6 / 1/6 | 3.78 / 4.12 / 4.67 | 42.44 / 33.73 / 2.78 | 13.71 / 34.40 / 24.61 | 12.41 / 12.98 / 16.56 | 0.0132 / 0.0124 / 0.0136 |
| constant all(gas and L1 wei) | 2 | 5.18 / 6.40 / 6.31 | 9.22 / 11.55* / 10.88* | 15.06* / 19.91* / 20.39* | 8.40 / 9.05 / 8.88 | 12.76* / 14.60* / 13.86* | 1/6 / 1/6 / 1/6 | 3.89 / 4.24 / 4.83 | 42.84 / 33.86 / 2.87 | 13.99 / 34.90 / 25.06 | 12.60 / 13.21 / 16.84 | 0.0128 / 0.0118 / 0.0128 |
| constant all(gas and L1 wei) | 3 | 5.51 / 6.83 / 6.78 | 11.59* / 14.59* / 13.68* | 20.34* / 27.09* / 27.91* | 8.76 / 9.51 / 9.38 | 15.32* / 17.86* / 16.88* | 1/6 / 1/6 / 1/6 | 4.12 / 4.48 / 5.16 | 43.64 / 34.13 / 3.04 | 14.58 / 35.90 / 25.97 | 12.97 / 13.69 / 17.39 | 0.012 / 0.0106 / 0.0114 |
| constant all(gas and L1 wei) | 5 | 6.18 / 7.70 / 7.74 | 16.35* / 20.67* / 19.26* | 30.90* / 41.46* / 42.96* | 9.48 / 10.42* / 10.39* | 20.43* / 24.38* / 22.92* | 1/6 / 1/6 / 1/6 | 4.56 / 4.95 / 5.83 | 45.27 / 34.67 / 3.38 | 15.75 / 37.91 / 27.80 | 13.73 / 14.65 / 18.53 | 0.0105 / 0.00811 / 0.00851 |
| constant all(gas and L1 wei) | 10 | 7.90 / 9.94 / 10.23* | 28.24* / 35.86* / 33.31* | 57.34* / 77.46* / 80.66* | 11.32* / 12.78* / 13.01* | 33.22* / 40.68* / 38.09* | 1/6 / 1/6 / 1/6 | 5.73 / 6.19 / 7.59 | 49.52 / 36.07 / 4.25 | 18.79 / 43.05 / 32.55 | 15.67 / 17.12 / 21.46 | 0.00651 / 0.0019 / 0.00106 |
| constant gas only | 1 | 4.84 / 5.97 / 5.84 | 6.84 / 8.51 / 8.10 | 9.79 / 12.72* / 12.88* | 8.05 / 8.59 / 8.39 | 10.20* / 11.34* / 10.85* | 1/6 / 1/6 / 1/6 | 3.67 / 4.00 / 4.51 | 42.05 / 33.60 / 2.70 | 13.42 / 33.90 / 24.16 | 12.22 / 12.74 / 16.29 | 0.0136 / 0.013 / 0.0143 |
| constant gas only | 1.5 | 5.00 / 6.17 / 6.06 | 8.02 / 10.02* / 9.48 | 12.42* / 16.30* / 16.63* | 8.21 / 8.81 / 8.62 | 11.47* / 12.95* / 12.34* | 1/6 / 1/6 / 1/6 | 3.77 / 4.12 / 4.66 | 42.42 / 33.73 / 2.78 | 13.68 / 34.33 / 24.56 | 12.40 / 12.96 / 16.54 | 0.0132 / 0.0124 / 0.0136 |
| constant gas only | 2 | 5.16 / 6.38 / 6.28 | 9.20 / 11.52* / 10.85* | 15.05* / 19.88* / 20.37* | 8.38 / 9.02 / 8.85 | 12.73* / 14.56* / 13.83* | 1/6 / 1/6 / 1/6 | 3.88 / 4.23 / 4.81 | 42.80 / 33.85 / 2.86 | 13.95 / 34.76 / 24.97 | 12.58 / 13.18 / 16.80 | 0.0129 / 0.0118 / 0.0129 |
| constant gas only | 3 | 5.48 / 6.78 / 6.73 | 11.55* / 14.54* / 13.62* | 20.31* / 27.04* / 27.86* | 8.72 / 9.45 / 9.32 | 15.27* / 17.79* / 16.82* | 1/6 / 1/6 / 1/6 | 4.09 / 4.45 / 5.12 | 43.56 / 34.11 / 3.02 | 14.48 / 35.61 / 25.78 | 12.93 / 13.63 / 17.32 | 0.0121 / 0.0107 / 0.0116 |
| constant gas only | 5 | 6.11 / 7.61 / 7.64 | 16.27* / 20.56* / 19.15* | 30.83* / 41.37* / 42.86* | 9.40 / 10.31* / 10.28* | 20.34* / 24.25* / 22.79* | 1/6 / 1/6 / 1/6 | 4.51 / 4.89 / 5.76 | 45.11 / 34.62 / 3.35 | 15.56 / 37.33 / 27.43 | 13.64 / 14.54 / 18.38 | 0.0106 / 0.00839 / 0.00881 |
| constant gas only | 10 | 7.74 / 9.72 / 10.00* | 28.05* / 35.61* / 33.05* | 57.18* / 77.24* / 80.44* | 11.13* / 12.53* / 12.76* | 33.01* / 40.39* / 37.81* | 1/6 / 1/6 / 1/6 | 5.61 / 6.05 / 7.41 | 49.16 / 35.96 / 4.20 | 18.35 / 41.76 / 31.71 | 15.47 / 16.86 / 21.13 | 0.00688 / 0.00251 / 0.00172 |
| sketch-only term | 1 | 4.84 / 5.97 / 5.84 | 6.84 / 8.51 / 8.10 | 9.79 / 12.72* / 12.88* | 8.05 / 8.59 / 8.39 | 10.20* / 11.34* / 10.85* | 1/6 / 1/6 / 1/6 | 3.67 / 4.00 / 4.51 | 42.05 / 33.60 / 2.70 | 13.42 / 33.90 / 24.16 | 12.22 / 12.74 / 16.29 | 0.0136 / 0.013 / 0.0143 |
| sketch-only term | 1.5 | 5.01 / 6.18 / 6.07 | 7.31 / 9.11 / 8.67 | 12.43* / 16.31* / 16.63* | 8.22 / 8.82 / 8.63 | 10.74* / 12.01* / 11.49* | 1/6 / 1/6 / 1/6 | 3.78 / 4.12 / 4.67 | 42.44 / 33.73 / 2.78 | 13.65 / 34.22 / 24.50 | 12.41 / 12.97 / 16.55 | 0.0132 / 0.0124 / 0.0136 |
| sketch-only term | 2 | 5.17 / 6.40 / 6.30 | 7.78 / 9.72 / 9.23 | 15.06* / 19.90* / 20.39* | 8.40 / 9.04 / 8.87 | 11.29* / 12.68* / 12.13* | 1/6 / 1/6 / 1/6 | 3.89 / 4.24 / 4.83 | 42.83 / 33.86 / 2.87 | 13.89 / 34.53 / 24.83 | 12.59 / 13.20 / 16.81 | 0.0128 / 0.0118 / 0.0129 |
| sketch-only term | 3 | 5.50 / 6.82 / 6.76 | 8.71 / 10.92* / 10.36* | 20.34* / 27.08* / 27.89* | 8.75 / 9.48 / 9.35 | 12.38* / 14.01* / 13.40* | 1/6 / 1/6 / 1/6 | 4.11 / 4.47 / 5.15 | 43.61 / 34.12 / 3.03 | 14.37 / 35.16 / 25.50 | 12.96 / 13.67 / 17.32 | 0.012 / 0.0106 / 0.0115 |
| sketch-only term | 5 | 6.16 / 7.68 / 7.67 | 10.59* / 13.32* / 12.63* | 30.88* / 41.44* / 42.89* | 9.44 / 10.37* / 10.30* | 14.56* / 16.69* / 15.95* | 1/6 / 1/6 / 1/6 | 4.55 / 4.94 / 5.79 | 45.18 / 34.64 / 3.36 | 15.32 / 36.42 / 26.84 | 13.69 / 14.60 / 18.36 | 0.0105 / 0.00818 / 0.0087 |
| sketch-only term | 10 | 7.81 / 9.82 / 9.97 | 15.27* / 19.32* / 18.28* | 57.25* / 77.34* / 80.40* | 11.19* / 12.60* / 12.68* | 20.02* / 23.39* / 22.33* | 1/6 / 1/6 / 1/6 | 5.65 / 6.12 / 7.38 | 49.09 / 35.94 / 4.19 | 17.70 / 39.56 / 30.20 | 15.53 / 16.93 / 20.95 | 0.00671 / 0.00223 / 0.00183 |

## 4. split multiple k* (conclusion first breaks multiple; "1" multiple 1 already, "> 100" searched range within none; in parentheses grid upper sign changes count)

| reference | case | constant all(gas and L1 wei) busy | constant all(gas and L1 wei) median | constant all(gas and L1 wei) quiet | constant gas only busy | constant gas only median | constant gas only quiet | sketch-only term busy | sketch-only term median | sketch-only term quiet |
|---|---|---|---|---|---|---|---|---|---|---|
| (i) sum > 10%, V 1 | lower | 15.7 (1) | 10.1 (1) | 9.56 (1) | 16.4 (1) | 10.7 (1) | 9.99 (1) | 16.6 (1) | 10.4 (1) | 10.1 (1) |
| (i) sum > 10%, V 1 | upper | 2.33 (1) | 1.49 (1) | 1.68 (1) | 2.34 (1) | 1.49 (1) | 1.69 (1) | 4.37 (1) | 2.24 (1) | 2.68 (1) |
| (i) sum > 10%, V 1 | facilitator | 1.04 (1) | 1 (0) | 1 (0) | 1.04 (1) | 1 (0) | 1 (0) | 1.04 (1) | 1 (0) | 1 (0) |
| (i) sum > 10%, V 0.2 | lower | 6.44 (1) | 4.08 (1) | 4.23 (1) | 6.75 (1) | 4.28 (1) | 4.42 (1) | 6.59 (1) | 4.16 (1) | 4.37 (1) |
| (i) sum > 10%, V 0.2 | upper | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) |
| (i) sum > 10%, V 0.2 | facilitator | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) |
| (ii) FB sum ≥ FI sum, V 1 | lower | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (ii) FB sum ≥ FI sum, V 1 | upper | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (ii) FB sum ≥ FI sum, V 1 | facilitator | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (iii) FR sum ≤ FB sum, lower V 1 | FR main | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (iii) FR sum ≤ FB sum, lower V 1 | FR lo | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |

(i) lower V 1, three window in all 10% within range end(constant all(gas and L1 wei)): k* = 9.56

(i) lower V 1, three window in all 10% within range end(constant gas only): k* = 9.99

(i) lower V 1, three window in all 10% within range end(sketch-only term): k* = 10.1

# reference B: P3 (b), per sale release 16,800 as measured values kept(multiple outside)

linear check(multiple 2, constant all): max relative difference 7.1e-16, release capacity unit changed cell 114 / 756.

## 5. per term share (revenue relative to %, chosen k; each cell term whole / its among sketch value share)


### six seller sum, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.23 / 0.00 | 0.29 / 0.00 | 0.29 / 0.00 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.41 / 0.09 | 1.90 / 0.09 | 2.01 / 0.12 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 5.94 / 0.10 | 7.46 / 0.12 | 7.41 / 0.14 |

### six seller sum, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.24 / 0.01 | 0.31 / 0.02 | 0.31 / 0.02 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 2.11 / 1.43 | 2.67 / 1.82 | 2.39 / 1.63 |
| release | sketch(reference B: per sale share only measured) | 1.98 / 0.65 | 2.64 / 0.83 | 2.65 / 0.75 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| detincl | estimated margin | 0.03 / 0.03 | 0.03 / 0.03 | 0.03 / 0.03 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 7.93 / 2.15 | 10.01 / 2.72 | 9.67 / 2.46 |

### six seller sum, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.23 / 0.00 | 0.29 / 0.00 | 0.29 / 0.00 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.41 / 0.09 | 1.90 / 0.09 | 2.01 / 0.12 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| facil | sketch | 4.94 / 4.94 | 6.75 / 6.75 | 7.04 / 7.04 |
| frozen | model(gas none) | 0.59 / 0.00 | 0.45 / 0.00 | 0.41 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 10.88 / 5.05 | 14.22 / 6.87 | 14.46 / 7.19 |

### six seller sum, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.15 / 0.00 | 1.36 / 0.01 | 1.38 / 0.01 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.43 / 0.11 | 1.92 / 0.11 | 2.03 / 0.14 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 9.14 / 0.13 | 10.09 / 0.14 | 9.96 / 0.17 |

### six seller sum, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.18 / 0.03 | 1.46 / 0.10 | 1.47 / 0.10 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 2.11 / 1.43 | 2.67 / 1.82 | 2.39 / 1.63 |
| release | sketch(reference B: per sale share only measured) | 2.00 / 0.67 | 2.66 / 0.85 | 2.66 / 0.77 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| detincl | estimated margin | 0.17 / 0.17 | 0.15 / 0.15 | 0.16 / 0.16 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| total | | 11.29 / 2.33 | 12.83 / 2.94 | 12.42 / 2.68 |

### six seller sum, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.15 / 0.00 | 1.36 / 0.01 | 1.38 / 0.01 |
| anchor | measured(G11) | 2.78 / 0.00 | 3.70 / 0.00 | 3.68 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.72 / 0.00 | 0.91 / 0.00 | 0.82 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.43 / 0.11 | 1.92 / 0.11 | 2.03 / 0.14 |
| l1 | sketch(L1 wei) | 0.02 / 0.02 | 0.02 / 0.02 | 0.02 / 0.02 |
| facil | sketch | 4.94 / 4.94 | 6.75 / 6.75 | 7.04 / 7.04 |
| frozen | model(gas none) | 2.87 / 0.00 | 2.01 / 0.00 | 1.87 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.16 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 14.08 / 5.07 | 16.84 / 6.89 | 17.01 / 7.21 |

### StableEnrich, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.09 / 0.02 | 1.14 / 0.03 | 1.59 / 0.04 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 4.55 / 0.04 | 4.92 / 0.04 | 5.79 / 0.06 |

### StableEnrich, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 1.25 / 0.85 | 1.72 / 1.17 | 1.58 / 1.07 |
| release | sketch(reference B: per sale share only measured) | 1.45 / 0.39 | 1.64 / 0.53 | 2.05 / 0.50 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| detincl | estimated margin | 0.03 / 0.03 | 0.03 / 0.03 | 0.03 / 0.03 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| total | | 5.77 / 1.29 | 6.59 / 1.75 | 7.32 / 1.63 |

### StableEnrich, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.21 / 0.00 | 0.21 / 0.00 | 0.21 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.09 / 0.02 | 1.14 / 0.03 | 1.59 / 0.04 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| facil | sketch | 3.94 / 3.94 | 4.15 / 4.15 | 5.74 / 5.74 |
| frozen | model(gas none) | 0.62 / 0.00 | 0.49 / 0.00 | 0.44 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.17 / 0.00 | 0.17 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 8.49 / 3.98 | 9.07 / 4.19 | 11.54 / 5.80 |

### StableEnrich, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.11 / 0.04 | 1.16 / 0.05 | 1.61 / 0.06 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 7.77 / 0.06 | 7.31 / 0.06 | 8.11 / 0.08 |

### StableEnrich, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 1.25 / 0.85 | 1.72 / 1.17 | 1.58 / 1.07 |
| release | sketch(reference B: per sale share only measured) | 1.47 / 0.41 | 1.66 / 0.55 | 2.07 / 0.52 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| detincl | estimated margin | 0.17 / 0.17 | 0.15 / 0.15 | 0.16 / 0.16 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| total | | 9.12 / 1.45 | 9.09 / 1.89 | 9.77 / 1.78 |

### StableEnrich, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 1.02 / 0.00 | 0.93 / 0.00 | 0.96 / 0.00 |
| anchor | measured(G11) | 2.01 / 0.00 | 2.31 / 0.00 | 2.82 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.43 / 0.00 | 0.59 / 0.00 | 0.54 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 1.11 / 0.04 | 1.16 / 0.05 | 1.61 / 0.06 |
| l1 | sketch(L1 wei) | 0.01 / 0.01 | 0.01 / 0.01 | 0.02 / 0.02 |
| facil | sketch | 3.94 / 3.94 | 4.15 / 4.15 | 5.74 / 5.74 |
| frozen | model(gas none) | 3.02 / 0.00 | 2.15 / 0.00 | 1.99 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.15 / 0.00 | 0.16 / 0.00 |
| capital | model(gas none) | 0.01 / 0.00 | 0.01 / 0.00 | 0.01 / 0.00 |
| total | | 11.71 / 4.00 | 11.45 / 4.21 | 13.85 / 5.82 |

### BlockRun, V 1, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 3.73 / 0.03 | 1.06 / 0.01 | 0.42 / 0.01 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 45.12 / 0.16 | 34.47 / 0.08 | 3.04 / 0.10 |

### BlockRun, V 1, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.03 / 0.02 | 0.02 / 0.01 | 0.39 / 0.27 |
| release | sketch(reference B: per sale share only measured) | 3.73 / 0.03 | 1.06 / 0.01 | 0.53 / 0.13 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| detincl | estimated margin | 0.03 / 0.03 | 0.02 / 0.02 | 0.03 / 0.03 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| total | | 45.17 / 0.21 | 34.51 / 0.12 | 3.44 / 0.51 |

### BlockRun, V 1, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.09 / 0.09 | 0.06 / 0.06 | 0.08 / 0.08 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 3.73 / 0.03 | 1.06 / 0.01 | 0.42 / 0.01 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| facil | sketch | 13.55 / 13.55 | 3.84 / 3.84 | 1.51 / 1.51 |
| frozen | model(gas none) | 36.26 / 0.00 | 31.84 / 0.00 | 1.51 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.12 / 0.00 | 0.15 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 58.67 / 13.71 | 38.31 / 3.92 | 4.55 / 1.61 |

### BlockRun, V 0.2, lower

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 3.75 / 0.05 | 1.07 / 0.02 | 0.43 / 0.02 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 98.21 / 0.52 | 78.98 / 0.26 | 5.05 / 0.21 |

### BlockRun, V 0.2, upper

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.03 / 0.02 | 0.02 / 0.01 | 0.39 / 0.27 |
| release | sketch(reference B: per sale share only measured) | 3.75 / 0.05 | 1.07 / 0.02 | 0.54 / 0.13 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| detincl | estimated margin | 0.17 / 0.17 | 0.09 / 0.09 | 0.07 / 0.07 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| total | | 98.40 / 0.71 | 79.09 / 0.37 | 5.49 / 0.66 |

### BlockRun, V 0.2, facilitator

| term | kind | busy | median | quiet |
|---|---|---|---|---|
| verify | mixed(tier 1a, 0: gas measured, L1 wei sketch; tier 0 history read estimated; upper tier 0 account node extrapolated) / TEE sketch | 0.43 / 0.43 | 0.23 / 0.23 | 0.18 / 0.18 |
| anchor | measured(G11) | 4.82 / 0.00 | 1.37 / 0.00 | 0.73 / 0.00 |
| sampvrf | mixed(lower: gas measured, L1 wei sketch; upper: request measured, Chainlink fulfillment sketch) | 0.01 / 0.00 | 0.01 / 0.00 | 0.13 / 0.00 |
| release | sketch(reference B: per sale share only measured) | 3.75 / 0.05 | 1.07 / 0.02 | 0.43 / 0.02 |
| l1 | sketch(L1 wei) | 0.04 / 0.04 | 0.01 / 0.01 | 0.00 / 0.00 |
| facil | sketch | 13.55 / 13.55 | 3.84 / 3.84 | 1.51 / 1.51 |
| frozen | model(gas none) | 88.99 / 0.00 | 76.20 / 0.00 | 3.49 / 0.00 |
| deduct_b | model(gas none) | 0.17 / 0.00 | 0.09 / 0.00 | 0.07 / 0.00 |
| capital | model(gas none) | 0.00 / 0.00 | 0.00 / 0.00 | 0.01 / 0.00 |
| total | | 111.76 / 14.07 | 82.82 / 4.10 | 6.56 / 1.72 |

## 6. multiple grid (window: busy / median / quiet; *  10% over)

| method | k | sum V1 lower | sum V1 upper | sum V1 facil | sum V0.2 lower | sum V0.2 upper | 10% within seller(V1 lower) | StableEnrich V1 lower | BlockRun V1 lower | FI sum V1 lower | FR main sum V1 lower | w* V1 lower |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constant all(gas and L1 wei) | 1 | 5.94 / 7.46 / 7.41 | 7.93 / 10.01* / 9.67 | 10.88* / 14.22* / 14.46* | 9.14 / 10.09* / 9.96 | 11.29* / 12.83* / 12.42* | 1/6 / 1/6 / 1/6 | 4.55 / 4.92 / 5.79 | 45.12 / 34.47 / 3.04 | 14.51 / 35.40 / 25.73 | 13.32 / 14.23 / 17.86 | 0.011 / 0.00878 / 0.00949 |
| constant all(gas and L1 wei) | 1.5 | 5.99 / 7.52 / 7.49 | 9.00 / 11.37* / 10.90* | 13.41* / 17.65* / 18.05* | 9.20 / 10.16* / 10.05* | 12.45* / 14.30* / 13.77* | 1/6 / 1/6 / 1/6 | 4.57 / 4.94 / 5.82 | 45.20 / 34.51 / 3.09 | 14.69 / 35.74 / 26.02 | 13.39 / 14.31 / 17.97 | 0.0109 / 0.00861 / 0.00927 |
| constant all(gas and L1 wei) | 2 | 6.04 / 7.58 / 7.56 | 10.08* / 12.73* / 12.13* | 15.93* / 21.09* / 21.64* | 9.27 / 10.23* / 10.13* | 13.62* / 15.77* / 15.11* | 1/6 / 1/6 / 1/6 | 4.59 / 4.97 / 5.85 | 45.28 / 34.55 / 3.14 | 14.86 / 36.08 / 26.31 | 13.46 / 14.40 / 18.09 | 0.0108 / 0.00845 / 0.00905 |
| constant all(gas and L1 wei) | 3 | 6.15 / 7.70 / 7.70 | 12.22* / 15.45* / 14.59* | 20.98* / 27.96* / 28.83* | 9.39 / 10.37* / 10.30* | 15.95* / 18.72* / 17.79* | 1/6 / 1/6 / 1/6 | 4.63 / 5.01 / 5.92 | 45.44 / 34.64 / 3.23 | 15.21 / 36.77 / 26.89 | 13.61 / 14.56 / 18.32 | 0.0106 / 0.00812 / 0.00862 |
| constant all(gas and L1 wei) | 5 | 6.35 / 7.94 / 7.99 | 16.52* / 20.90* / 19.51* | 31.07* / 41.70* / 43.21* | 9.65 / 10.66* / 10.64* | 20.60* / 24.61* / 23.17* | 1/6 / 1/6 / 1/6 | 4.70 / 5.09 / 6.04 | 45.76 / 34.81 / 3.43 | 15.92 / 38.15 / 28.05 | 13.90 / 14.89 / 18.78 | 0.0101 / 0.00746 / 0.00775 |
| constant all(gas and L1 wei) | 10 | 6.88 / 8.53 / 8.72 | 27.25* / 34.51* / 31.82* | 56.31* / 76.05* / 79.15* | 10.29* / 11.38* / 11.50* | 32.24* / 39.33* / 36.61* | 1/6 / 1/6 / 1/6 | 4.90 / 5.32 / 6.35 | 46.57 / 35.23 / 3.92 | 17.72 / 41.64 / 31.04 | 14.65 / 15.72 / 19.94 | 0.00887 / 0.00581 / 0.00557 |
| constant gas only | 1 | 5.94 / 7.46 / 7.41 | 7.93 / 10.01* / 9.67 | 10.88* / 14.22* / 14.46* | 9.14 / 10.09* / 9.96 | 11.29* / 12.83* / 12.42* | 1/6 / 1/6 / 1/6 | 4.55 / 4.92 / 5.79 | 45.12 / 34.47 / 3.04 | 14.51 / 35.40 / 25.73 | 13.32 / 14.23 / 17.86 | 0.011 / 0.00878 / 0.00949 |
| constant gas only | 1.5 | 5.98 / 7.51 / 7.47 | 8.99 / 11.36* / 10.89* | 13.40* / 17.64* / 18.04* | 9.19 / 10.15* / 10.03* | 12.44* / 14.29* / 13.75* | 1/6 / 1/6 / 1/6 | 4.56 / 4.94 / 5.81 | 45.18 / 34.51 / 3.09 | 14.66 / 35.67 / 25.97 | 13.38 / 14.30 / 17.96 | 0.0109 / 0.00865 / 0.00931 |
| constant gas only | 2 | 6.02 / 7.56 / 7.53 | 10.06* / 12.70* / 12.11* | 15.91* / 21.06* / 21.62* | 9.25 / 10.20* / 10.11* | 13.60* / 15.74* / 15.08* | 1/6 / 1/6 / 1/6 | 4.57 / 4.95 / 5.84 | 45.24 / 34.54 / 3.13 | 14.81 / 35.94 / 26.22 | 13.44 / 14.37 / 18.05 | 0.0108 / 0.00852 / 0.00913 |
| constant gas only | 3 | 6.11 / 7.65 / 7.65 | 12.18* / 15.40* / 14.54* | 20.94* / 27.91* / 28.78* | 9.35 / 10.32* / 10.25* | 15.90* / 18.66* / 17.73* | 1/6 / 1/6 / 1/6 | 4.60 / 4.98 / 5.88 | 45.36 / 34.62 / 3.22 | 15.12 / 36.48 / 26.70 | 13.57 / 14.50 / 18.24 | 0.0106 / 0.00826 / 0.00877 |
| constant gas only | 5 | 6.28 / 7.84 / 7.89 | 16.43* / 20.79* / 19.40* | 31.00* / 41.60* / 43.11* | 9.57 / 10.55* / 10.53* | 20.51* / 24.48* / 23.04* | 1/6 / 1/6 / 1/6 | 4.65 / 5.04 / 5.96 | 45.60 / 34.76 / 3.41 | 15.73 / 37.57 / 27.68 | 13.82 / 14.77 / 18.63 | 0.0102 / 0.00773 / 0.00805 |
| constant gas only | 10 | 6.71 / 8.31 / 8.49 | 27.06* / 34.26* / 31.56* | 56.15* / 75.84* / 78.93* | 10.11* / 11.13* / 11.25* | 32.03* / 39.05* / 36.32* | 1/6 / 1/6 / 1/6 | 4.78 / 5.18 / 6.17 | 46.20 / 35.13 / 3.87 | 17.29 / 40.35 / 30.20 | 14.45 / 15.46 / 19.62 | 0.00924 / 0.00641 / 0.00624 |

## 7. split multiple k* (conclusion first breaks multiple; "1" multiple 1 already, "> 100" searched range within none; in parentheses grid upper sign changes count)

| reference | case | constant all(gas and L1 wei) busy | constant all(gas and L1 wei) median | constant all(gas and L1 wei) quiet | constant gas only busy | constant gas only median | constant gas only quiet |
|---|---|---|---|---|---|---|---|
| (i) sum > 10%, V 1 | lower | 39.1 (1) | 22.1 (1) | 18.8 (1) | 46.6 (1) | 27.5 (1) | 22.2 (1) |
| (i) sum > 10%, V 1 | upper | 1.96 (1) | 1 (0) | 1.13 (1) | 1.97 (1) | 1 (0) | 1.13 (1) |
| (i) sum > 10%, V 1 | facilitator | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) |
| (i) sum > 10%, V 0.2 | lower | 7.72 (1) | 1 (0) | 1.21 (1) | 8.98 (1) | 1 (0) | 1.25 (1) |
| (i) sum > 10%, V 0.2 | upper | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) |
| (i) sum > 10%, V 0.2 | facilitator | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) | 1 (0) |
| (ii) FB sum ≥ FI sum, V 1 | lower | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (ii) FB sum ≥ FI sum, V 1 | upper | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (ii) FB sum ≥ FI sum, V 1 | facilitator | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (iii) FR sum ≤ FB sum, lower V 1 | FR main | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |
| (iii) FR sum ≤ FB sum, lower V 1 | FR lo | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) | > 100 (0) |

(i) lower V 1, three window in all 10% within range end(constant all(gas and L1 wei)): k* = 18.8

(i) lower V 1, three window in all 10% within range end(constant gas only): k* = 22.2
