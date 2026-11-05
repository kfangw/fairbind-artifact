#!/usr/bin/env python3
"""K12: k11b.py with a bundle size N (facilitator delegation, R8 of rule candidate v0.7z). New file copied from k11b.py
(k11b.py is not changed and not imported). Computation rules were fixed before this run in K12_calc-rules.md.
Added: Prm fields bun (bundle size N, default 1), asc (anchor scenario S, M, Z), peer (P1, P2); Grid._bundle_anchor,
Grid._fvrf, Grid._rho and their use in Grid._c0. With bun = 1 (and asc != 'Z') every new factor is skipped, so the
file gives the K11b numbers (output sec. 1 compares them with K11/k11b_output.md cell by cell).
Run: python3 -I docs/11_journal/K12/k12.py   (writes k12_output.md only)
Original K11b header follows.
K11b: k11.py with the gas constants of the events measured in G11 (G11_gas.md incl. sec. 6 caveat) replacing the sketch
values (K11b_settings.md, fixed before this run). New file copied from k11.py (k11.py is not changed and not imported). Only
constants change: set_gas("new") below; set_gas("old") restores the K11 constants and output sec. 1 reproduces the
cells of k11_output.md with them. Sensitivities L, W, U, C are set_gas variants (K11b_settings.md sec. 2).
Run: python3 -I docs/11_journal/K11/k11b.py   (writes k11b_output.md only)
Original K11 header follows.

K11: the K10h cost model (lower and upper cases) recomputed with the parameters of rule candidate v0.7p and the two
chain modes of decision D1 (K11_settings.md, fixed before this run). New self-contained file built from k10h.py (it does
not import k10h.py). Changes against k10h.py:
 (1) deduction b = V (Prm bV=True; k10h used bond(V) = ceil(V / 0.675 * 1e6) / 1e6, about 40/27 V);
 (2) anchor deadline, VRF window, T_p, T_c are fields of Prm (DA, SV, TP, TC); H(k) = 300k + DA + SV + TP + TC,
     DF = 300 + DA + SV + TP (K10h (b)); the EIP-2935 admission check uses 300 + DA;
 (3) mode N (normal): DA 120, SV 31, TP 1,800, TC 1,800; mode S (safe head, windows >= 12 h): DA 90,600, SV 22,651,
     TP 24,420, TC 24,420, and OneSource priced with the signed-feed proof (t0rs) because tier 0 fails check (5);
 (4) data: the R10 lists are not in this workspace; per-epoch counts of busy and median come from
     data/processed/agg_2026-10-21/epochs_{busy,median}.csv.gz (StableEnrich part uses the full seller's counts) and
     the active profile epochs of the partial sellers are the list values printed in k10h_output.md sec. 2; with the
     old parameters this reproduces k10h_output.md (output sec. 1).
Run: python3 -I docs/11_journal/K11/k11.py   (writes k11_output.md only)
Original K10h header follows.
K10h: K10g with four corrections from the round-6 empirical review (Q20/review6_empirical.md M1 to M3), each a switch of
Prm; with fpe=df1=e2935=curpe=False (the dict OFF) the file is K10g exactly (output sec. 1 and sec. 10 compare it cell
by cell with k10g_output.md). New self-contained file built from k10g.py (it does not import k10g.py).
Rule: rule10-candidate/rule10-candidate_v0.5_frame-and-rules.md; manuscript sections/sec_rule.tex, app_rule.tex.
 (a) fpe: the facilitator's first-sale surcharge (17,074 gas, the settle that creates a new accumulator/count slot) is
     charged once per active profile epoch E_p (was E(k), per seller epoch). R3 (a) checks the anchor's entry count
     against the settlement count of each profile epoch, and sec_rule l.113 makes that count the contract's own, so
     settle keeps a per-profile-epoch slot; G10c settle (the measured 17,074) keys the accumulator by (receiving
     address, 300-block epoch). R6 (b) indexes the accumulator A_{a,E,k} by seller epoch E and release unit k (k there
     is the release unit, not the multiplier); a separate per-seller-epoch slot would add on top of E_p and is not
     charged (K10h_results.md sec. 1).
 (b) df1: the wrongful-failure frozen interval is DF(1) = 300 + 20 + 31 + T_p for every k (was DF(k)). R7 (b) freezes
     sales settled at or after s_f; the case expires at M_e + T_p of its profile epoch and R4 (b) lets the failure be
     declared there by the cursor or by the separate failure declaration of an expired case (app_rule: required call);
     the account is then suspended (R7 (c)). H(k) for capital is unchanged.
 (c) e2935: the tier-0 EIP-2935 admission check (rule 0-1 (c), app_rule admission check (5): epoch length plus anchor
     deadline <= 8,191 - margin) uses the profile epoch, EPB + DA = 320 blocks; the k-based exclusion (EPB k + DA >
     8,000 drops k 32 for the storage-proof seller) is removed.
 (d) curpe: upper case only, the cursor's fixed release cost F (and its L1 fixed part) is charged per active profile
     epoch, E_p + E_r(1) units, because the cursor checks conditions (0) to (3) for every profile epoch of a seller
     epoch (R6 (a), sec_rule l.113) while the measured release (G10c) covers one epoch; no saving from k. The lower
     case keeps F per active seller epoch (E(k) + E_r(k)).
 (e) empty profile epochs: no anchor, no sample value, the cursor passes them (sec_rule l.113 "A profile epoch with no
     settlement needs no anchor and no sample value"); no cost, as in K10g. Documented only.
Each seller still picks k in {1, 2, 4, 8, 16, 32} with the least total.
Output sec. 9 lists every manuscript cost figure, before (K10g = OFF, the manuscript now) and after (K10h).
Run: python3 -I docs/11_journal/K_revision-cost/K10/k10h.py   (writes k10h_output.md only)
Original K10g header follows.
K10g: K10f with the anchor, the sample request and the random value charged once per active *profile* epoch
(rule rule10-candidate v0.5 R1 (a): profile epochs are global 300-block intervals and the anchor, the sample value and W_e are
per profile epoch; R3 (a) anchor and R4 (a) sample per profile epoch; R6 (a) only the release cursor works per seller
epoch of k profile epochs). Prompted by the empirical review of Table S6 (StableEnrich 82.6 sales "per epoch" was
n / E(8), the seller-epoch count). New self-contained file built from k10f.py (it does not import k10f.py).
THE CHANGE (Prm(pe=True), the default; pe=False is K10f exactly, checked cell by cell in output sec. 1):
  K10f charged, for each k, with E(k) = active seller epochs (min(E1, ceil(N_ep / k)), or the D3 epochs table for D94):
    anchor transactions A = E(k) + E_a(k) (fixed gas, per-sale gas at x = n / A, anchor L1), E_a(k) = extra units of
    the k-grouped counts; sample request + random value (ECVRF lower, Chainlink VRF v2.5 upper) E(k) times;
    release E(k) + E_r(k) times.
  K10g charges, for every k,
    anchor transactions A_p = E_p + E_a,p with E_p = E(1), the number of active profile epochs, and E_a,p = E_a(1), the
      extra units of the per-profile-epoch counts (R10 lists, D3 epochs table, or the summary bound with k = 1);
      per-sale anchor gas at x = n / A_p; anchor L1 likewise (all independent of k);
    sample request + random value E_p times (both cases);
    release E(k) + E_r(k) times, per active seller epoch, as before.
  Unchanged: H(k), DF(k) (the cursor still waits for the whole seller epoch), frozen, deduction and capital terms,
  facilitator first-sale gas E(k) (the settle accumulator is per seller epoch, R6 (b)), the upper allowance (A),
  the multipliers 2.0, 1.10, 1.56, w values, sets, EIP-2935 exclusion of k 32 for the tier-0 proof.
  Each seller still picks k in {1, 2, 4, 8, 16, 32} with the least total; k now trades only release fixed gas against
  locked-money terms.
Output sec. 9 lists every cost figure the manuscript takes from K10e/K10f, with pe=False (= the manuscript) and pe=True.
Run: python3 -I docs/11_journal/K_revision-cost/K10/k10g.py   (writes k10g_output.md only)
Original K10f header follows.
K10f: K10e cost model plus (A) an upper-bound gas allowance for the parts still missing from the measured sketches
and (B) the per-endpoint tier correction of the main set (Q20/review4_empirical.md M4 and M5; K10f_results.md sec. 1, deviation K10f-1).
New self-contained file built from k10e.py (it does not import k10e.py). With up=False and the K10e sets it is K10e
(the lower case); output sec. 1 reproduces k10e_output.md sec. 5, 7 and 8 cell by cell.
 (A) Upper case (Prm(up=True)), from the manuscript's and G10/G10b's own unit costs, all under the L2 multiplier:
   1. per proof call (n_s per seller): determinism and EXTCODEHASH check, 2,600 (cold EXTCODEHASH) + 2,600 (one more
      cold account for a registered library call, upper) = 5,200 gas, plus Merkle inclusion of the anchored leaf,
      depth x 900 gas (manuscript "about 900 gas per Merkle level"; G10b swap-proof marginal 796, G10 883), depth =
      ceil(log2(anchor capacity)) = 10 (sigma 1, 924 sales) or 11 (sigma 0, 1,564), an upper bound for any anchor;
      sensitivity: inclusion per anchored sale (n instead of n_s);
   2. failure path (freeze and deduction) once per episode: 21,000 + 18,536 (G10b lazy failure in the release call,
      k=1 expired minus k=1 closed: freeze start, suspension, deduction writes) + 64,740 (the deduction moved as one
      USDC transfer, x402 transferWithAuthorization 85,740 - 21,000) = 104,276 gas, charged (1 + w n_s) times per
      seller and window;
   3. production ECVRF margin: the per-epoch randomness is priced at the Chainlink VRF v2.5 figure (G10d 3.5) as the
      upper option;
   4. tier-0 storage proof at Base depth: 552,125 + 4 x 29,976 (account nodes 6 to 10, G10b sec. 2.3) = 672,029 gas.
 (B) Corrected tiers (set T01t, "tier-0/1 endpoint revenue of the classified data sellers"): per-endpoint tiers of
   F1 (supplementary Table S1); StableEnrich without its sales of 1 USDC or more (the identifiable candidate for the
   domain-registration branch, tier Out; busy window 11 sales, 16.50 USDC); OneSource (tier 0) priced with the tier-0
   storage proof (G10b 552,125 gas + 5,000 history read; RedStone as sensitivity) and k 32 excluded (EIP-2935).
(K10f run line: python3 -I .../k10f.py, writes k10f_output.md)
"""
import sys, os, csv, gzip, json, math, hashlib, subprocess, copy
import numpy as np
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
K10D = os.path.abspath(os.path.join(HERE, '..', 'K_revision-cost', 'K10'))
J = os.path.abspath(os.path.join(HERE, '..'))
F = J + '/F'
DOCS = os.path.abspath(os.path.join(J, '..'))
K11D = os.path.abspath(os.path.join(HERE, '..', 'K11'))
SET_MD = HERE + '/K12_calc-rules.md'
PRICE = DOCS + '/05_run-evidence/R7R8/out/R9/R9-5/price_cache.json'
SUMCSV = F + '/data-review/target_sellers_all_summary.csv'
VALCSV = F + '/data-review/target_sellers_values.csv'
MEDD = DOCS + '/05_run-evidence/design2/median-period/seed0'
OBS1 = MEDD + '/base_v1_auto-zero-reject/condition-01-seed-0/addresses_observed.csv'
OBS02 = MEDD + '/base_v0.2_auto-zero-reject/condition-01-seed-0/addresses_observed.csv'
MEMB = F + '/I4_loss-reimpl/d3_members.json'
ROOT = os.path.abspath(os.path.join(DOCS, '..'))
AGG = ROOT + '/data/processed/agg_2026-10-21'
EPOCHS = AGG + '/epochs_median.csv.gz'
G10B_L1 = J + '/G10_gas/logs_b/g10b_l1fee.tsv.gz'
G10C_L1 = J + '/G10_gas/logs_c/g10c_l1fee.tsv.gz'
G10C_SUM = J + '/G10_gas/logs_c/g10c_summary.tsv.gz'
G10C_BIG = J + '/G10_gas/logs_c/g10c_l1fee_big.tsv.gz'
G10D_VRF = J + '/G10_gas/logs_d/g10d_vrf.tsv.gz'
G10D_MD = J + '/G10_gas/G10d_gas.md'
G11D = J + '/G11_gas'
G11_L1 = G11D + '/logs/p5_l1fee.tsv.gz'
K11_OUT = K11D + '/k11_output.md'
K11B_OUT = K11D + '/k11b_output.md'
LISTS = os.environ.get('R10_LISTS', './r10-lists')          # R10 lists (R10 registration 2.1; not committed)
LISTW = {'median': ('settlements_base_2026-07-24_2026-08-13.csv', 49030927, 49938126),
         'busy': ('settlements_base_2026-06-09_2026-06-29.csv', 47086928, 47994126)}

out = []
P = out.append

# ------------------------------------------------------------------ K10 / K10c constants (k10c.py)
ETH_K10, GW_K10 = 1890.0, 0.006
G_REL_K10, G_SEAL_K10 = 105_161, 208_152
B_SEAL, B_REL, ENV = 68, 36, 110
KS = [1, 2, 4, 8, 16, 32]
EPB = 300; DA = 20; SMP = 31; TP0, TC0 = 1_800, 1_800
EIP2935_OK = 8_000
G_BH_READ = 5_000
X402B = 85_740
FACX_K10C = {'lo': 149_136 - X402B, 'hi': 238_100}

# ------------------------------------------------------------------ G10b and G10c rows, read by label
def read_tsv(path):
    d = {}
    with gzip.open(path, 'rt') as fh:
        head = fh.readline()
        for r in csv.DictReader(fh, delimiter='\t'): d[r['label']] = r
    return head, d
_, RB = read_tsv(G10B_L1)
_, RC = read_tsv(G10C_L1)
_, RCB = read_tsv(G10C_BIG)
with gzip.open(G10C_SUM, 'rt') as fh:
    SENS = dict(kv.split('=') for kv in fh.readline().strip().split('sensitivity inputs ')[1].split())
SENS = {k: float(v) for k, v in SENS.items()}
def tg(d, lab): return int(d[lab]['tx_gas'])
def tw(d, lab): return int(d[lab]['l1_fee_node_wei'])
AL = lambda n, s: 'G10-5 anchor n=%d %s snapshot=1, tx gas' % (n, 'all signed a=0' if s else 'no buyer sigs')
A8 = {s: tg(RB, AL(8, s)) for s in (0, 1)}; A32 = {s: tg(RB, AL(32, s)) for s in (0, 1)}
assert A8 == {0: 201_331, 1: 274_156} and A32 == {0: 417_429, 1: 650_180}
G10B_M = {0: 9_004, 1: 15_668}                                         # G10b sec. 2.3
G10B_F = {s: A8[s] - 8 * G10B_M[s] for s in (0, 1)}                    # 129,299 / 148,812
FL8 = {0: 113_160, 1: 136_620}; FL32 = {0: 368_280, 1: 462_120}       # EIP-7623 floor of the same rows (G10b)
FL_M = {s: (FL32[s] - FL8[s]) / 24 for s in (0, 1)}
FL_F = {s: FL8[s] - 8 * FL_M[s] for s in (0, 1)}
L1W8 = {s: tw(RB, AL(8, s)) for s in (0, 1)}; L1W32 = {s: tw(RB, AL(32, s)) for s in (0, 1)}
L1W_M = {s: (L1W32[s] - L1W8[s]) / 24 for s in (0, 1)}
L1W_F = {s: L1W8[s] - 8 * L1W_M[s] for s in (0, 1)}
CPL = {'TEE': 'G10-1 single receipt, snapshot mapping, tx gas', 'PY1': 'G10-3 Pyth Lazer-shaped update, 1 feed(s), tx gas',
       'RS3': 'G10-3 RedStone-shaped, 3 package(s) of 1 point, tx gas', 'SP0': 'G10-4 full: header, account and storage proof, tx gas'}
CPG = {k: (tg(RB, l), tw(RB, l)) for k, l in CPL.items()}
# G10c
SL = 'G10c-1 settle, %s, %s sale of the epoch, tx gas'
SETTLE = {rd: {'first': tg(RC, SL % (rd, 'first')) - X402B, 'later': tg(RC, SL % (rd, 'later')) - X402B} for rd in ('ledger', 'pool')}
assert SETTLE == {'ledger': {'first': 78_617, 'later': 61_543}, 'pool': {'first': 89_807, 'later': 72_733}}
assert all(tw(RC, SL % (rd, f)) == tw(RC, SL % (rd, 'later')) for rd in ('ledger', 'pool') for f in ('first',))
G_REQ = tg(RC, 'G10c-2 sample request (per profile epoch, after A_e), tx gas')               # 51,550
W_REQ = tw(RC, 'G10c-2 sample request (per profile epoch, after A_e), tx gas')
G_VRF_MEAS = tg(RC, 'G10c-2 VRF value acceptance (verify, store, event), tx gas')            # 90,182 (4 tries)
W_VRF = tw(RC, 'G10c-2 VRF value acceptance (verify, store, event), tx gas')
G_VRF_EXP = 80_900                                                                            # G10c 3.2, 2 tries (computed)
RLL = 'G10c-2 release epoch, %s, m=%d sales, k=%d closed cases, tx gas'
REL_M, REL_K = 2_930, 2_083                                                                   # G10c 3.3
REL_F = {'pool': 105_742, 'ledger': 105_742 + 8_882}
for rd in ('pool', 'ledger'):                                                                 # formula against the measured rows
    for m_, k_ in ((8, 4), (32, 4), (8, 0)):
        assert abs(REL_F[rd] + REL_M * m_ + REL_K * k_ - tg(RC, RLL % (rd, m_, k_))) <= 0.005 * tg(RC, RLL % (rd, m_, k_))
RW_M = (tw(RC, RLL % ('ledger', 128, 4)) - tw(RC, RLL % ('ledger', 8, 4))) / 120                # release L1 wei per sale
RW_F = tw(RC, RLL % ('ledger', 8, 4)) - 8 * RW_M
CAP_GAS = {1: 924, 0: 1_564}; CAP_TXP = {1: 271, 0: 339}; TX_CAP = 2 ** 24; TXPOOL = 131_072
REL_CAP_TXP = (TXPOOL - 100) // 160                                                           # release: 160 calldata bytes per sale
# measured anchor curve (G10c 4.2, G10b rows), sensitivity
MEAS = {1: [(8, A8[1]), (32, A32[1])] + [(n, tg(RC if AL(n, 1) in RC else RCB, AL(n, 1))) for n in (64, 128, 256, 512, 768, 900, 920)],
        0: [(8, A8[0]), (32, A32[0])] + [(n, tg(RC if AL(n, 0) in RC else RCB, AL(n, 0))) for n in (64, 128, 256, 512, 1024, 1300, 1450, 1560)]}
# ------------------------------------------------------------------ G10d (K10e changes 1 and 2)
MULT_MAIN = 2.0                                   # G10d 0, 2.4: pooled p50 (and p90) of egp / 0.005 gwei
MULT_SENS = {'median window 1.10': 1.10, 'whole sample 1.56': 1.56, 'multiple none 1.0 (K10d)': 1.0}
TIP_REF = 0.005                                   # gwei; the multiplier is defined on this basis
def _vrf_rows():
    with gzip.open(G10D_VRF, 'rt') as fh:
        fh.readline()
        return [r for r in csv.DictReader(fh, delimiter='\t')]
VR = _vrf_rows()
_nat = [r for r in VR if r['mode'] == 'native' and int(r['rep']) >= 2]           # steady rows (G10d 3.3)
_b = np.polyfit([int(r['h2c_tries']) for r in _nat], [int(r['billed_gas']) for r in _nat], 1)
CL_BILL_FIT = (int(round(_b[1])), int(round(_b[0])))                              # 129,437 + 5,539 t
CL_BILL_EXP = CL_BILL_FIT[0] + 2 * CL_BILL_FIT[1]                                 # 140,515 (expected 2 tries)
assert CL_BILL_FIT == (129_437, 5_539) and CL_BILL_EXP == 140_515, CL_BILL_FIT
CL_L1_CHARGED = int(_nat[0]['l1_cost_wei']); assert CL_L1_CHARGED == 4_321_371_668 and all(int(r['l1_cost_wei']) == CL_L1_CHARGED for r in VR)
for r in _nat:                                    # fee formula against the measured payments (native, 0.005 gwei)
    assert int(r['payment']) == (int(r['fulfill_gas_price']) * int(r['billed_gas']) + int(r['l1_cost_wei'])) * 160 // 100
CL_NEWSLOT = 17_129                               # G10d 3.3, 3.5: callback writes a new slot every epoch
CL_BILL = CL_BILL_EXP + CL_NEWSLOT                # 157,644
CL_REQ = 96_000                                   # G10d 3.5: requestSample 51,550 + coordinator frame 41,778 + call overhead (computed)
CL_PREM = 1.60                                    # nativePremiumPercentage 60 (s_config)
CL_REQ_MIN = int(_nat[0]['request_gas'])          # 72,122 (minimal consumer, measured), for the G10d 3.4 check
# ------------------------------------------------------------------ K10f upper-bound allowance (A), read by row label
SWL = 'G10-2 swap proof, epoch of %d entries (depth %d), tx gas'
G_LVL_G10B = (tg(RB, SWL % (65536, 16)) - tg(RB, SWL % (8, 3))) / 13                      # 796.1 (G10b, current rules)
assert round(G_LVL_G10B) == 796, G_LVL_G10B
G_LVL = 900                                       # manuscript VII-A "about 900 gas per Merkle level" (>= 796 and G10's 883)
G_COLD = 2_600                                    # manuscript VII-A: cold account access (EIP-2929)
G_DET = 2 * G_COLD                                # EXTCODEHASH of the verification contract + one more cold account (library)
G_FAIL_CALL = (tg(RB, 'G10-5 release one sale, k=1 expired cases (lazy failure, sale frozen), tx gas')
               - tg(RB, 'G10-5 release one sale, k=1 closed cases, tx gas'))                # 18,536
assert G_FAIL_CALL == 18_536, G_FAIL_CALL
X402_TX = tg(RB, 'G10b-7 plain x402 transferWithAuthorization, payTo paid before, tx gas')   # 85,740
assert X402_TX == X402B
G_FAIL = 21_000 + G_FAIL_CALL + (X402_TX - 21_000)                                            # 104,276
ACCL = 'G10-4 account proof of %d nodes (%d bytes), tx gas'
SP0_NODE = (tg(RB, ACCL % (8, 2377)) - tg(RB, ACCL % (5, 2146))) / 3                          # 29,976
SP0_UP = CPG['SP0'][0] + 4 * SP0_NODE                                                        # 10 account nodes (Base) vs 6
assert round(SP0_NODE) == 29_976 and abs(SP0_UP - 672_029) < 2, (SP0_NODE, SP0_UP)
OUT_MIN = 1.0                                     # (B) StableEnrich sales >= 1 USDC: domain-registration candidate (Out)
def depth_of(cap): return 16 if cap == math.inf else int(math.ceil(math.log2(cap)))

G_OPEN = tg(RB, 'G10-6 open dispute 1 KB, tx gas'); G_DEC = tg(RB, 'G10-6 decryption check, misbehaviour proven 4 KB, tx gas')
W_OPEN = tw(RB, 'G10-6 open dispute 1 KB, tx gas'); W_DEC = tw(RB, 'G10-6 decryption check, misbehaviour proven 4 KB, tx gas')
DEP0 = 0                                          # Merkle levels already inside the measured proof call (upper allowance)
# ------------------------------------------------------------------ G11 rows (K11b_settings.md sec. 1)
_, RG = read_tsv(G11_L1)
def gg(lab): return int(RG[lab]['tx_gas'])
def gf(lab): return int(RG[lab]['eip7623_floor'])
def gw(lab): return int(RG[lab]['l1_fee_node_wei'])
SELF = 'P5 self-submission, one unit, m=%d %s, tx gas'
VRFQ = 'P5 shared SAMPLE request (set), tx gas'; VRFA = 'P5 shared (set 2) value acceptance (ECVRF), tries 2, tx gas'
VRFC = 'P5 shared SAMPLE request through Chainlink VRF v2.5 (set, native), tx gas'
T1A = 'P5 proof call, tier 1a Pyth Pro one feed, depth 5, tx gas'; T0 = 'P5 proof call, tier 0 storage proof (fixture), depth 5, tx gas'
DOP = 'P5 non-delivery dispute (honest seller), open, depth 5, 1 KB, tx gas'
DDC = 'P5 non-delivery dispute (misbehaving seller), decryption challenge, refund, 4 KB, tx gas'
# ------------------------------------------------------------------ K12 bundle constants (K12_calc-rules.md sec. 3), G11 rows
BUN = 'P5 bundled anchor, P=%d profiles, m=32 all signed, tx gas'
REL1 = 'P5 release one account, m=8 sales, k=4 cases, tx gas'
RELB = 'P5 bundled release, N=%d accounts, m=8 sales, k=4 cases each, tx gas'
_A32 = gg(SELF % (32, 'all signed'))
WRAP = gg(BUN % 1) - _A32                                            # 3,252: bundle header of one transaction
MX = [1, 2, 4, 8]
MY = [0.0] + [gg(BUN % p) / p - _A32 for p in (2, 4, 8)]             # per-unit change measured by G11 (P = 2, 4, 8)
TXBASE = 21_000
ZSAVE = 3 * 22_100                                                   # scenario Z: five stored slots -> two
REL_DIRECT = gg(REL1)
REL_MARG = (gg(RELB % 8) - gg(RELB % 1)) / 7                         # 60,441 per added account
REL_A_M = REL_MARG / REL_DIRECT                                      # measured form: a = 0.5837
REL_A_S = 0.6                                                        # sketch form (K12_calc-rules.md 3.3)

BASIS = {'g10b': (0.005, 2401.44), 'k10': (GW_K10, ETH_K10),
         'bf99': (SENS['bf_p99'] * 1e-9, 2401.44), 'bfmax': (SENS['bf_max'] * 1e-9, 2401.44),
         'eth95': (0.005, SENS['eth_p95']), 'bfmax_eth95': (SENS['bf_max'] * 1e-9, SENS['eth_p95'])}
BASN = {'g10b': 'G10b reference', 'k10': 'K10 reference(0.006 gwei, 1,890)', 'bf99': 'base fee 99th percentile %.5f gwei' % (SENS['bf_p99'] * 1e-9),
        'bfmax': 'base fee maximum %.4f gwei' % (SENS['bf_max'] * 1e-9), 'eth95': 'ETH 95th percentile %.2f' % SENS['eth_p95'],
        'bfmax_eth95': 'base fee maximum and ETH 95th percentile'}

pc = json.load(open(PRICE))
L1R = sum(b['l1_fee_sum'] for b in pc['blocks']) / sum(b['l1_gas_sum'] for b in pc['blocks'])
def l1u(cd, txs=1.0): return 16 * (cd + ENV * txs)
def bond(V, p0=1.0): return math.ceil(V / (0.675 * p0) * 1e6) / 1e6
def f3(x): return x if isinstance(x, str) else ('nan' if x != x else '%.3f' % x)
def f4(x): return x if isinstance(x, str) else '%.4f' % x
def g3(x): return x if isinstance(x, str) else '%.3g' % x
def fmt(x): return format(int(round(x)), ',')
def sha8(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:8] if os.path.exists(p) else 'absent'


# ------------------------------------------------------------------ parameters of one run
class Prm:
    def __init__(self, **kw):
        d = dict(mode='k10d', basis='g10b', sig=1.0, fac=False, rd='ledger', vrf=G_VRF_EXP, cap='gas', anc='lin', cpm='main',
                 l1m=1.0, k10c_fac=False, a=0.0, mult=MULT_MAIN, rnd='ecvrf', up=False, incl='proof', glvl=G_LVL, sp0up=True, pe=True,
                 fpe=True, df1=True, e2935=True, curpe=True, bV=True, DA=120, SV=31, TP=TP0, TC=TC0, t0rs=False, bun=1, asc='S', peer='P1')
        d.update(kw)
        if d['mode'] == 'k10c': d['basis'] = 'k10'; d['mult'] = 1.0
        self.__dict__.update(d)
        self.key = tuple(sorted(d.items()))
        self.gw, self.eth = BASIS[self.basis]
        self.gp = self.gw + (self.mult - 1.0) * TIP_REF                      # effective L2 gas price, gwei
    def gusd(self, gas): return gas * self.gp * 1e-9 * self.eth
    def cl_usd(self):                                                         # Chainlink VRF v2.5 per epoch, incl. L1
        return self.gusd(CL_REQ) + self.wusd(W_REQ) + CL_PREM * (self.gusd(CL_BILL) + self.wusd(CL_L1_CHARGED))
    def ecvrf_usd(self): return self.gusd(G_REQ + self.vrf) + self.wusd(W_REQ + W_VRF)
    def rand_usd(self): return self.cl_usd() if self.rnd == 'cl' else self.ecvrf_usd()
    def wusd(self, wei): return wei * 1e-18 * self.eth * self.l1m
    def l1usd_k10(self, units): return units * L1R * 1e-18 * self.eth * self.l1m
    def cpu(self, key):
        g, w = CPG[key]
        if key == 'SP0' and self.up and self.sp0up: g = SP0_UP
        return self.gusd(g) + self.wusd(w) + (self.gusd(G_BH_READ) if key == 'SP0' else 0.0)
    def H(self, k): return EPB * k + self.DA + self.SV + self.TP + self.TC
    def DF(self, k): return EPB * k + self.DA + self.SV + self.TP
OFF = dict(fpe=False, df1=False, e2935=False, curpe=False)   # K10h switches off = K10g


# ------------------------------------------------------------------ data (k10c.py)
PERIODS = [('busy', 's1b', 'busy', 21), ('median', 's1b', 'median', 21), ('quiet', 's1c', 'quiet', 15)]
PDAYS = {p: d for p, _, _, d in PERIODS}
SUMALL = {}
for r in csv.DictReader(open(SUMCSV, encoding='ascii')):
    for p, src, win, _ in PERIODS:
        if r['source'] == src and r['window'] == win: SUMALL.setdefault(p, []).append(r)
VAL = {}
for r in csv.DictReader(open(VALCSV, encoding='ascii')):
    for p, src, win, _ in PERIODS:
        if r['source'] == src and r['window'] == win:
            up = math.inf if r['upper_usdc'] == 'inf' else float(r['upper_usdc'])
            VAL.setdefault((p, r['seller']), []).append((up, int(r['sales']), float(r['usdc'])))
EDGES = [0.0, 0.001, 0.01, 0.1, 0.2, 0.5, 1.0, 5.0, math.inf]


def ns_group(c, u, lo_e, up_e, V, end='hi'):
    if c <= 0: return 0.0
    if up_e <= V + 1e-12: return u / V
    if lo_e >= V - 1e-12: return float(c)
    hi = min(float(c), u / V)
    lo = max(c * min(1.0, lo_e / V), (u / up_e) if up_e < math.inf else 0.0)
    return hi if end == 'hi' else min(lo, hi)


ADDR = {'StableEnrich': '0x325bdf6f7efab24a2210c48c1b64cab2eae1d430', 'OneSource': '0x52e29e0d2aa49bfbfc548c0a9f2196f4aa51f3ea',
        'CoinMarketCap': '0x3c5f3a6ce224bb89d72f5eb4232ecc27f67b3eea', 'StableApify': '0x23d931f95831cee50b5f5edf4d0e88270f6c8411',
        'Exa': '0x6d6e695b09861467c7d462f5aaf31cf3540b9192', 'CoinStats': '0x0750a9e669c37fe1a1847e4b8f9e16f07c16162f',
        'BlockRun': '0xe9030014f5dae217d0a152f02a043567b16c1abf'}
T01_FULL = ['StableEnrich', 'OneSource', 'CoinMarketCap', 'StableApify']
T01_PART = {'Exa': 0.001, 'CoinStats': 0.01}          # endpoint part = value bins with upper <= this
TIER0 = {'OneSource'}                                  # R10c 3.1 (CoinStats wallet 0.004 part is inside the <= 0.01 bin)
T01T_PART = {'StableEnrich': 0.5}                      # (B) StableEnrich in-tier part: value bins up to 0.5 (Out = sales >= 1 USDC)
SCANPART = dict(T01_PART, **T01T_PART)


# ------------------------------------------------------------------ per-epoch counts from the R10 lists (busy, median)
def scan_lists():
    cnt, info = {}, {}
    inv = {v: k for k, v in ADDR.items()}
    for w, (fn, first, last) in LISTW.items():
        path = '%s/%s/%s' % (LISTS, w, fn)
        if not os.path.exists(path): info[w] = 'missing'; continue
        nep = (last - first) // EPB + 1
        arr = {k: np.zeros(nep) for k in list(ADDR) + [nm + '|part' for nm in SCANPART]}
        tot = {k: [0, 0] for k in arr}
        cmd = ['grep', '-F'] + sum([['-e', a] for a in ADDR.values()], []) + [path]
        pr = subprocess.run(cmd, stdout=subprocess.PIPE, env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}, check=True)
        for line in pr.stdout.decode().splitlines():
            c = line.split(',')
            nm = inv.get(c[5].lower())
            if nm is None: continue
            e = (int(c[0]) - first) // EPB; v = int(c[7])
            arr[nm][e] += 1; tot[nm][0] += 1; tot[nm][1] += v
            if nm in SCANPART and v <= round(SCANPART[nm] * 1e6):
                arr[nm + '|part'][e] += 1; tot[nm + '|part'][0] += 1; tot[nm + '|part'][1] += v
        for k in arr: cnt[(w, k)] = arr[k]
        info[w] = {k: (t[0], t[1] / 1e6) for k, t in tot.items()}
    return cnt, info


LCNT, LINFO = scan_lists()
for w in ('busy', 'median'):
    if LINFO.get(w) != 'missing': continue
    inv = {v: k for k, v in ADDR.items()}; nep = 21 * 144
    arr = {k: np.zeros(nep) for k in ADDR}
    for r in csv.DictReader(gzip.open('%s/epochs_%s.csv.gz' % (AGG, w), 'rt')):
        nm = inv.get(r['recipient'].lower())
        if nm is not None: arr[nm][int(r['epoch'])] += int(r['n'])
    for k in arr: LCNT[(w, k)] = arr[k]
    LCNT[(w, 'StableEnrich|part')] = arr['StableEnrich']
PART_E1 = {('busy','StableEnrich'):2046,('busy','Exa'):195,('busy','CoinStats'):16,('median','StableEnrich'):2178,('median','Exa'):220,('median','CoinStats'):11}


def splits_from_counts(c, k, cap):
    m = np.bincount(np.arange(len(c)) // k, weights=c)
    m = m[m > 0]
    return float(np.sum(np.maximum(np.ceil(m / cap) - 1, 0)))


def splits_bound(n, E, m1, k, cap):
    """no per-epoch counts: upper bound on extra units. An epoch with m sales needs ceil(m/cap) - 1 extra units."""
    mk = min(k * m1, n)
    if mk <= cap: return 0.0
    return float(min(math.ceil(n / cap) - 1, E * (math.ceil(mk / cap) - 1)))


def t13_entry(p, r, name, V, part=None):
    B = VAL.get((p, r['seller']), [])
    if part is not None: B = [b for b in B if b[0] <= part + 1e-12]
    n = sum(b[1] for b in B); R = sum(b[2] for b in B)
    ns = sum(ns_group(c, u, EDGES[EDGES.index(up) - 1], up, V) for up, c, u in B)
    lk = None
    if p in LISTW and (p, (name + '|part') if part is not None else name) in LCNT:
        lk = LCNT[(p, (name + '|part') if part is not None else name)]
    if part is None:
        n0, R0 = int(r['sales']), float(r['usdc'])
        assert n == n0 and abs(R - R0) < 0.01, (p, name)
        E1 = min(int(r['active_epochs']), n); m1 = int(r['max_epoch_sales'])
    else:
        if (p, name) in PART_E1: E1 = PART_E1[(p, name)]; m1 = min(int(r['max_epoch_sales']), n)
        elif lk is not None: E1 = int((lk > 0).sum()); m1 = int(lk.max())
        elif (p, name) in PART_E1: E1 = PART_E1[(p, name)]; m1 = min(int(r['max_epoch_sales']), n)
        else: E1 = min(int(r['active_epochs']), n); m1 = min(int(r['max_epoch_sales']), n)
    return dict(a=name if part is None else '%s(%g or less)' % (name, part), base=name, R=R, n=n, ns=ns, E1=E1, m1=m1, cnt=lk,
                tier0=(name in TIER0 and part is None), rs=1.0 / len(SUMALL[p]))


def t13_sellers(st, p, V):
    o = []
    rows = {r['seller']: r for r in SUMALL[p]}
    if st == 'old':
        for r in SUMALL[p]:
            if r['category'] != 'data': continue
            e = t13_entry(p, r, r['seller'], V); e['tier0'] = False
            if e['R'] > 0 and e['n'] > 0: o.append(e)
    elif st in ('T01', 'T01s', 'T01x'):
        for nm in T01_FULL:
            if st == 'T01x' and nm == 'StableEnrich': continue
            if nm in rows: o.append(t13_entry(p, rows[nm], nm, V))
        for nm, thr in (T01_PART.items() if st in ('T01', 'T01x') else []):
            if nm in rows:
                e = t13_entry(p, rows[nm], nm, V, part=thr)
                if e['n'] > 0: o.append(e)
    elif st == 'T01t':                                   # (B) per-endpoint tiers
        for nm in T01_FULL:
            if nm not in rows: continue
            if nm in T01T_PART:
                e = t13_entry(p, rows[nm], nm, V, part=T01T_PART[nm]); e['a'] = nm + '(Out candidates excluded)'
            else:
                e = t13_entry(p, rows[nm], nm, V)
            if e['n'] > 0: o.append(e)
        for nm, thr in T01_PART.items():
            if nm in rows:
                e = t13_entry(p, rows[nm], nm, V, part=thr)
                if e['n'] > 0: o.append(e)
    elif st == 'BR':
        o.append(t13_entry(p, rows['BlockRun'], 'BlockRun', V))
    return o


# ------------------------------------------------------------------ D94 (k10c.py)
memb = json.load(open(MEMB))
D94 = [a.lower() for a in memb['median|0.2|main']]
assert len(D94) == 94
D94S = set(D94)
O1 = {r['address'].lower(): r for r in csv.DictReader(open(OBS1, encoding='ascii')) if r['address'].lower() in D94S}
O02 = {r['address'].lower(): r for r in csv.DictReader(open(OBS02, encoding='ascii')) if r['address'].lower() in D94S}
SEP = {a: {} for a in D94}
for r in csv.DictReader(gzip.open(EPOCHS, 'rt', newline='')):
    a = r['recipient'].lower()
    if a in D94S and int(r['n']) >= 1: SEP[a][int(r['epoch'])] = SEP[a].get(int(r['epoch']), 0) + int(r['n'])
def d94_epoch_k(k):
    grp = {a: {e // k for e in v} for a, v in SEP.items()}
    m = {}
    for a, g in grp.items():
        for x in g: m[x] = m.get(x, 0) + 1
    cnt = {a: len(g) for a, g in grp.items()}
    rs = {a: (sum(1.0 / m[x] for x in g) / len(g) if g else 1.0) for a, g in grp.items()}
    return cnt, rs
EK = {k: d94_epoch_k(k) for k in KS}
def d94_splits(a, k, cap):
    mm = {}
    for e, c in SEP[a].items(): mm[e // k] = mm.get(e // k, 0) + c
    return float(sum(max(math.ceil(c / cap) - 1, 0) for c in mm.values()))
IV = lambda r, c: int(r[c]) if r[c] not in ('', None) else 0


def d94_sellers(V):
    o = []
    for a in D94:
        r1, r2 = O1[a], O02[a]
        acc1n, acc1v = IV(r1, 'accepted_count'), IV(r1, 'accepted_value') / 1e6
        cr1n, cr1v = IV(r1, 'cap_rejected_count'), IV(r1, 'cap_rejected_value') / 1e6
        acc2n, acc2v = IV(r2, 'accepted_count'), IV(r2, 'accepted_value') / 1e6
        cr2n = IV(r2, 'cap_rejected_count')
        E1 = IV(r1, 'epochs_with_settlement')
        n = acc1n + cr1n; R = acc1v + cr1v
        if V == 0.2: ns = acc2v / 0.2 + cr2n
        elif V == 0.5: ns = acc2v / 0.5 + ns_group(acc1n - acc2n, acc1v - acc2v, 0.2, 1.0, 0.5) + cr1n
        elif V == 1.0: ns = acc1v + cr1n
        else: ns = acc1v / V + ns_group(cr1n, cr1v, 1.0, math.inf, V)
        if R <= 0 or n <= 0: continue
        o.append(dict(a=a, base=a, R=R, n=n, ns=ns, E1=max(E1, 1), tier0=False))
    return o


# ------------------------------------------------------------------ anchor gas
def anc_lin(sg, x):
    ex = (1 - sg) * (G10B_F[0] + G10B_M[0] * x) + sg * (G10B_F[1] + G10B_M[1] * x)
    fl = (1 - sg) * (FL_F[0] + FL_M[0] * x) + sg * (FL_F[1] + FL_M[1] * x)
    return np.maximum(ex, fl), fl > ex


def anc_meas(sg, x):
    def one(s, xx):
        pts = MEAS[s]; xs = np.array([p[0] for p in pts], float); ys = np.array([p[1] for p in pts], float)
        lin = np.maximum(G10B_F[s] + G10B_M[s] * xx, FL_F[s] + FL_M[s] * xx)
        return np.where(xx < xs[0], lin, np.interp(xx, xs, ys))
    return (1 - sg) * one(0, x) + sg * one(1, x)


def cap_anchor(prm):
    if prm.cap == 'none': return math.inf
    c = CAP_GAS if prm.cap == 'gas' else CAP_TXP
    sg = prm.sig
    if sg in (0.0, 1.0): return float(c[int(sg)])            # exact (1/(1/1564) is 1563.99... in floating point)
    return float(math.floor(1.0 / ((1 - sg) / c[0] + sg / c[1])))


# ------------------------------------------------------------------ grid
class Grid:
    def __init__(self, st, V, prm):
        self.st, self.V, self.prm = st, V, prm
        kind, _, per = st.partition(':')
        self.kind = kind
        if kind == 'D94': self.days = 21; S = d94_sellers(V)
        else: self.days = PDAYS[per]; S = t13_sellers(kind, per, V)
        self.ok = len(S) > 0
        if not self.ok: return
        self.S = S; self.N = len(S); self.Wb = self.days * 43200; Nep = self.days * 144; self.Nep = Nep; self.bund = {}
        self.a_ = [s['a'] for s in S]
        self.R = np.array([s['R'] for s in S]); self.n = np.array([float(s['n']) for s in S]); self.ns = np.array([s['ns'] for s in S])
        self.b = float(V) if prm.bV else bond(V)
        self.ks = KS
        nk = len(KS)
        E = np.empty((nk, self.N)); rs = np.empty_like(E); Ua = np.zeros_like(E); Ur = np.zeros_like(E)
        self.t0 = np.array([s['tier0'] for s in S])
        if prm.mode == 'k10d' and kind == 'T01t':          # (B): tier-0 storage proof for OneSource; 'rs3' is the sensitivity
            ck = ['RS3' if (prm.cpm == 'rs3' or prm.t0rs) else ('SP0' if s['tier0'] else 'RS3') for s in S]
        elif prm.mode == 'k10d':
            if prm.cpm == 'main': ck = ['TEE' if kind == 'BR' else 'RS3' for s in S]
            elif prm.cpm == 'tier': ck = ['TEE' if kind == 'BR' else ('SP0' if s['tier0'] else 'RS3') for s in S]
            else: ck = ['RS3' for s in S]
        else:
            ck = ['RS3' for s in S]
        self.ck = ck
        self.cp = np.array([prm.cpu(c) for c in ck])
        capA = cap_anchor(prm)
        q = self.ns / self.n
        if prm.cap == 'none': capR = np.full(self.N, math.inf)
        elif prm.cap == 'gas': capR = np.floor((TX_CAP - REL_F[prm.rd]) / (REL_M + REL_K * np.minimum(q, 1.0)))
        else: capR = np.full(self.N, float(REL_CAP_TXP))
        self.capA, self.capR = capA, capR
        self.esrc = []
        for i, k in enumerate(KS):
            for j, s in enumerate(S):
                if kind == 'D94':
                    cnt1, cnt, r_ = EK[1][0][s['a']], EK[k][0][s['a']], EK[k][1][s['a']]
                    E[i, j] = s['E1'] * cnt / cnt1 if cnt1 else float(s['E1']); rs[i, j] = r_
                else:
                    E[i, j] = min(s['E1'], math.ceil(Nep / k)); rs[i, j] = s['rs']
                if prm.mode == 'k10d':
                    if kind == 'D94':
                        Ua[i, j] = d94_splits(s['a'], k, capA) if capA < math.inf else 0.0
                        Ur[i, j] = d94_splits(s['a'], k, capR[j]) if capR[j] < math.inf else 0.0
                        if i == 0: self.esrc.append('D3 epoch Table')
                    elif s['cnt'] is not None:
                        Ua[i, j] = splits_from_counts(s['cnt'], k, capA) if capA < math.inf else 0.0
                        Ur[i, j] = splits_from_counts(s['cnt'], k, capR[j]) if capR[j] < math.inf else 0.0
                        if i == 0: self.esrc.append('R10 list')
                    else:
                        Ua[i, j] = splits_bound(s['n'], E[i, j], s['m1'], k, capA) if capA < math.inf else 0.0
                        Ur[i, j] = splits_bound(s['n'], E[i, j], s['m1'], k, capR[j]) if capR[j] < math.inf else 0.0
                        if i == 0: self.esrc.append('upper bound(summary max)')
        self.E, self.rs, self.Ua, self.Ur = E, rs, Ua, Ur
        self.Hk = np.array([prm.H(k) for k in KS], float)[:, None]
        self.DFk = np.array([prm.DF(1 if prm.df1 else k) for k in KS], float)[:, None]   # K10h (b)
        # tier 0 sellers: k with H(k) above the EIP-2935 window are not allowed (k10c tier-0 variant drops k 32)
        # K10h (c): with e2935 the admission check uses the profile epoch (EPB + DA), so no k is excluded
        self.bad = np.zeros_like(E, bool)
        if prm.mode == 'k10d':
            for i, k in enumerate(KS):
                if (EPB if prm.e2935 else EPB * k) + prm.DA > EIP2935_OK: self.bad[i, :] = [ck[j] == 'SP0' for j in range(self.N)]
        self.c0parts = self._c0()
        self.c0 = sum(self.c0parts.values())

    def _f(self, q, m):
        if self.prm.peer == 'P1': return 1.0 / m
        q = np.clip(q, 1e-12, 1.0)
        return (1.0 - (1.0 - q) ** m) / (m * q)

    def _lim(self):
        return self.prm.bun if self.prm.asc != 'M' else min(self.prm.bun, 8)

    def _bundle_anchor(self, ag, fb, Ep):
        prm = self.prm
        if prm.asc == 'Z': ag = ag - ZSAVE
        if prm.bun <= 1: return ag
        self.bund['floor_bind'] = bool(np.any(fb))
        m = np.maximum(1.0, np.minimum(float(self._lim()), np.floor(TX_CAP / ag)))
        if prm.asc == 'M':
            assert prm.peer == 'P1'
            delta = np.interp(m, MX, MY)
        else:
            delta = np.where(m > 1, -TXBASE + (TXBASE + WRAP) * self._f(Ep / self.Nep, m), 0.0)
        self.m_a = m
        return ag + delta

    def _fvrf(self, Ep):
        if self.prm.bun <= 1: return 1.0
        return self._f(Ep / self.Nep, float(self.prm.bun))

    def _rho(self, Ru, n, ns, q):
        prm = self.prm
        if prm.bun <= 1: return 1.0
        a = REL_A_M if prm.asc == 'M' else REL_A_S
        unit = REL_F[prm.rd] + (REL_M * n[None, :] + REL_K * ns[None, :]) / Ru
        m = np.maximum(1.0, np.minimum(float(self._lim()), np.floor(TX_CAP / unit)))
        self.m_r = m
        return np.where(m > 1, a + (1 - a) * self._f(q, m), 1.0)

    def _c0(self):
        prm, R, n, ns, E = self.prm, self.R, self.n, self.ns, self.E
        sg = prm.sig
        parts = {}
        parts['verify'] = np.broadcast_to(self.cp * ns / R, E.shape).copy()
        if prm.mode == 'k10c':                          # K10c (k10c.py with anc g10b): no splits, shared seal, release 105,161
            nbar = n[None, :] / E
            ag, fb = anc_lin(sg, nbar); self.flb = fb
            parts['anchor'] = prm.gusd(E * ag) / R
            parts['seal'] = prm.gusd(E * self.rs * G_SEAL_K10) / R
            parts['release'] = prm.gusd(G_REL_K10 * E) / R
            aw = (1 - sg) * (L1W_F[0] + L1W_M[0] * nbar) + sg * (L1W_F[1] + L1W_M[1] * nbar)
            parts['l1'] = (prm.wusd(E * aw) + prm.l1usd_k10(E * self.rs * l1u(B_SEAL) + E * l1u(B_REL))) / R
            if prm.k10c_fac:
                parts['facil'] = np.broadcast_to(prm.gusd(FACX_K10C[prm.k10c_fac]) * n / R, E.shape).copy()
            return parts
        if prm.pe:                                       # K10g: anchor and random value per active profile epoch (k = 1 counts)
            assert KS[0] == 1
            Ep = np.broadcast_to(E[0][None, :], E.shape).copy()
            A = np.broadcast_to((E[0] + self.Ua[0])[None, :], E.shape).copy()
        else:                                            # K10f: per active seller epoch
            Ep = E; A = E + self.Ua
        self.Ep, self.Ap = Ep, A
        x = n[None, :] / A
        if prm.anc == 'lin': ag, fb = anc_lin(sg, x)
        else: ag = anc_meas(sg, x); fb = np.zeros_like(x, bool)
        self.flb = fb
        ag = self._bundle_anchor(ag, fb, Ep)
        parts['anchor'] = prm.gusd(A * ag) / R
        parts['sampvrf'] = Ep * prm.rand_usd() * self._fvrf(Ep) / R                                   # randomness incl. its L1 (K10d kept that L1 in 'l1')
        if prm.up and prm.curpe:                         # K10h (d): upper case, release fixed cost per active profile epoch
            Ru = np.broadcast_to((E[0] + self.Ur[0])[None, :], E.shape).copy()
        else:
            Ru = E + self.Ur
        self.Ru = Ru
        if prm.up and prm.curpe: qr = Ep / self.Nep
        else: qr = E / np.ceil(self.Nep / np.array(KS, float))[:, None]
        parts['release'] = prm.gusd(Ru * REL_F[prm.rd] * self._rho(Ru, n, ns, qr) + REL_M * n[None, :] + REL_K * ns[None, :]) / R
        aw = A * ((1 - sg) * L1W_F[0] + sg * L1W_F[1]) + n[None, :] * ((1 - sg) * L1W_M[0] + sg * L1W_M[1])
        parts['l1'] = prm.wusd(aw + Ru * RW_F + RW_M * n[None, :]) / R
        if prm.fac:
            Ef = np.minimum(Ep if prm.fpe else E, n[None, :])   # K10h (a)
            parts['facil'] = prm.gusd(Ef * SETTLE[prm.rd]['first'] + (n[None, :] - Ef) * SETTLE[prm.rd]['later']) / R
        if prm.up:                                       # (A) upper-bound allowance
            dep = depth_of(self.capA)
            nin = ns if prm.incl == 'proof' else n
            parts['detincl'] = np.broadcast_to(prm.gusd(G_DET * ns + max(dep - DEP0, 0) * prm.glvl * nin) / R, E.shape).copy()
            parts['failpath'] = np.broadcast_to(prm.gusd(G_FAIL) / R, E.shape).copy()
        return parts

    def loss(self, w):
        lam = w * self.ns[None, :] * self.DFk / self.Wb
        frz = (1 - self.prm.a) * (1 - np.exp(-lam))
        ded = np.broadcast_to(w * self.ns * self.b / self.R, frz.shape)
        if self.prm.up and self.prm.mode == 'k10d':      # (A) failure path for each expected wrongful failure
            ded = ded + w * self.ns * self.prm.gusd(G_FAIL) / self.R
        return frz, ded

    def cap(self, r):
        return r * (self.b + (1 - self.prm.a) * self.R[None, :] / self.Wb * self.Hk) * (self.days / 365.0) / self.R[None, :]

    def total(self, w, r=0.10):
        frz, ded = self.loss(w)
        t = self.c0 + frz + ded + self.cap(r)
        return np.where(self.bad, np.inf, t)

    def opt(self, w, r=0.10):
        tot = self.total(w, r)
        ki = np.argmin(tot, axis=0); j = np.arange(self.N)
        sel = tot[ki, j]
        return dict(ki=ki, tot=sel, agg=float((sel * self.R).sum() / self.R.sum()), med=float(np.median(sel)))

    def comp(self, w, r=0.10):
        o = self.opt(w, r); ki = o['ki']; j = np.arange(self.N)
        frz, ded = self.loss(w); cp = self.cap(r)
        d = {k: v[ki, j] for k, v in self.c0parts.items()}
        d['frozen'] = frz[ki, j]; d['deduct'] = ded[ki, j]; d['capital'] = cp[ki, j]; d['total'] = o['tot']
        Rs = self.R.sum()
        return {k: (float((v * self.R).sum() / Rs), float(np.median(v))) for k, v in d.items()}, o, d

    def wstar(self, which, r=0.10, th=0.10):
        if self.prm.mode == 'k10c' and self.cp[0] / self.V >= th: return 'none(verification)'
        fn = lambda w: self.opt(w, r)[which]
        if fn(0.0) > th: return 'none(w 0)'
        lo, hi = 0.0, 1.0
        if fn(hi) <= th: return '> 1'
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if fn(mid) <= th: lo = mid
            else: hi = mid
        return lo


_G = {}
def G(st, V, prm):
    key = (st, V, prm.key)
    if key not in _G: _G[key] = Grid(st, V, prm)
    return _G[key]
def PD(sg, fac=False, **kw): return Prm(sig=sg, fac=fac, **kw)
def rng(xs):
    num = [x for x in xs if not isinstance(x, str)]; strs = [x for x in xs if isinstance(x, str)]
    if not num: return strs[0] if strs else '-'
    s = '%s ~ %s' % (g3(min(num)), g3(max(num))) if len(num) > 1 else g3(num[0])
    return s + ('' if not strs else ' (partial %s)' % strs[0])
def rngf(xs): return '%s ~ %s' % (f3(min(xs)), f3(max(xs))) if len(xs) > 1 else f3(xs[0])


PER = ['busy', 'median', 'quiet']
WTT_D = [0.0, 0.00173, 0.002, 0.005, 0.01]
SETN = {'T01t': 'classified data seller tier 0/1 endpoint revenue', 'T01': 'tier 0 and 1 data', 'T01s': 'tier 0 and 1 data, seller four only', 'T01x': 'tier 0 and 1 data, StableEnrich excluded', 'old': 'K10 data(comparison)', 'D94': 'D94', 'BR': 'BlockRun(tier 1b)'}
def sname(st):
    k, _, p = st.partition(':')
    return SETN[k] + ('' if not p else ' ' + {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}[p])
SETS_ALL = ['T01t:' + p for p in PER] + ['T01:' + p for p in PER] + ['T01s:' + p for p in PER] + ['T01x:' + p for p in PER] + ['old:' + p for p in PER] + ['D94'] + ['BR:' + p for p in PER]


# ------------------------------------------------------------------ gas sets (K11b_settings.md sec. 1 and 2)
GNAMES = ['G10B_F', 'G10B_M', 'FL_F', 'FL_M', 'L1W_F', 'L1W_M', 'G_REQ', 'G_VRF_EXP', 'CL_REQ', 'CPG', 'SP0_UP', 'G_OPEN', 'G_DEC',
          'W_OPEN', 'W_DEC', 'W_REQ', 'W_VRF', 'G_DET', 'DEP0', 'CAP_GAS']
OLDG = {n: copy.deepcopy(globals()[n]) for n in GNAMES}
SGN = {1: 'all signed', 0: 'none signed'}


def new_values(L1=False, wrap=False, dedup=False, cap=False):
    d = {}
    A8_ = {s: gg(SELF % (8, SGN[s])) for s in (0, 1)}; A32_ = {s: gg(SELF % (32, SGN[s])) for s in (0, 1)}
    M = {s: (A32_[s] - A8_[s]) / 24 for s in (0, 1)}
    d['G10B_M'] = M; d['G10B_F'] = {s: A8_[s] - 8 * M[s] for s in (0, 1)}
    f8 = {s: gf(SELF % (8, SGN[s])) for s in (0, 1)}; f32 = {s: gf(SELF % (32, SGN[s])) for s in (0, 1)}
    d['FL_M'] = {s: (f32[s] - f8[s]) / 24 for s in (0, 1)}; d['FL_F'] = {s: f8[s] - 8 * d['FL_M'][s] for s in (0, 1)}
    d['G_REQ'] = gg(VRFQ); d['G_VRF_EXP'] = gg(VRFA); d['CL_REQ'] = gg(VRFC)
    cpg = copy.deepcopy(OLDG['CPG'])
    cpg['RS3'] = (gg(T1A), OLDG['CPG']['RS3'][1]); cpg['SP0'] = (gg(T0), OLDG['CPG']['SP0'][1])
    d['SP0_UP'] = gg(T0) + 4 * SP0_NODE
    d['G_OPEN'] = gg(DOP); d['G_DEC'] = gg(DDC)
    d['L1W_M'] = OLDG['L1W_M']; d['L1W_F'] = OLDG['L1W_F']
    d['W_REQ'] = OLDG['W_REQ']; d['W_VRF'] = OLDG['W_VRF']; d['W_OPEN'] = OLDG['W_OPEN']; d['W_DEC'] = OLDG['W_DEC']
    if L1:                                            # sensitivity L: L1 data cost wei of the same rows
        w8 = {s: gw(SELF % (8, SGN[s])) for s in (0, 1)}; w32 = {s: gw(SELF % (32, SGN[s])) for s in (0, 1)}
        d['L1W_M'] = {s: (w32[s] - w8[s]) / 24 for s in (0, 1)}; d['L1W_F'] = {s: w8[s] - 8 * d['L1W_M'][s] for s in (0, 1)}
        cpg['RS3'] = (gg(T1A), gw(T1A)); cpg['SP0'] = (gg(T0), gw(T0))
        d['W_REQ'] = gw(VRFQ); d['W_VRF'] = gw(VRFA); d['W_OPEN'] = gw(DOP); d['W_DEC'] = gw(DDC)
    if wrap:                                          # sensitivity W: the FairBind share of the stage 1a call added to RS3 and TEE
        share = gg(T1A) - OLDG['CPG']['PY1'][0]
        cpg['RS3'] = (OLDG['CPG']['RS3'][0] + share, OLDG['CPG']['RS3'][1]); cpg['TEE'] = (OLDG['CPG']['TEE'][0] + share, OLDG['CPG']['TEE'][1])
    d['CPG'] = cpg
    d['G_DET'] = OLDG['G_DET']; d['DEP0'] = OLDG['DEP0']
    if dedup: d['G_DET'] = 0; d['DEP0'] = 5           # sensitivity U
    d['CAP_GAS'] = copy.deepcopy(OLDG['CAP_GAS'])
    if cap:                                           # sensitivity C
        s = (gg(SELF % (128, SGN[1])) - A32_[1]) / 96
        d['CAP_GAS'] = {1: 32 + int((TX_CAP - A32_[1]) // s),
                        0: int((TX_CAP - d['G10B_F'][0]) // (M[0] * s / M[1]))}
    return d


GASSETS = {'old': lambda: dict(OLDG), 'new': lambda: new_values(), 'L': lambda: new_values(L1=True), 'W': lambda: new_values(wrap=True),
           'U': lambda: new_values(dedup=True), 'C': lambda: new_values(cap=True)}
def set_gas(name):
    for n, v in GASSETS[name]().items(): globals()[n] = copy.deepcopy(v)
    _G.clear()

# ================================================================== K11 report
MODES = {
    'OLD': dict(bV=False, DA=20, SV=31, TP=1_800, TC=1_800),             # K10h
    'b only': dict(bV=True, DA=20, SV=31, TP=1_800, TC=1_800),
    'a_A only': dict(bV=False, DA=120, SV=31, TP=1_800, TC=1_800),
    'N': dict(bV=True, DA=120, SV=31, TP=1_800, TC=1_800),
    'S': dict(bV=True, DA=90_600, SV=22_651, TP=24_420, TC=24_420, t0rs=True),
    'S-d': dict(bV=True, DA=45_300, SV=22_651, TP=24_420, TC=24_420, t0rs=True),
    'S-120': dict(bV=True, DA=120, SV=22_651, TP=24_420, TC=24_420),
}
CH = {   # chain-layer and deadline values of each mode (K11_settings.md 2.1, 2.2)
    'N': dict(d_inc=30, m_a=30, a_F=60, a_A=120, SV=31, TP=1_800, TC=1_800, T_rs=1_770, w_b=1_800, T_x=30),
    'S': dict(d_inc=22_650, m_a=22_650, a_F=45_300, a_A=90_600, SV=22_651, TP=24_420, TC=24_420, T_rs=1_770, w_b=22_651, T_x=22_650),
    'S-d': dict(d_inc=22_650, m_a=22_650, a_F=None, a_A=45_300, SV=22_651, TP=24_420, TC=24_420, T_rs=1_770, w_b=22_651, T_x=22_650),
    'S-120': dict(d_inc=22_650, m_a=30, a_F=60, a_A=120, SV=22_651, TP=24_420, TC=24_420, T_rs=1_770, w_b=22_651, T_x=22_650),
}
W0 = 0.00173
def LOm(m, fac=False, **kw): d = dict(MODES[m]); d.update(kw); return PD(1.0, fac, **d)
def UPm(m, fac=False, **kw):
    d = dict(MODES[m]); d.update(dict(rnd='cl')); d.update(kw); return PD(1.0, fac, up=True, **d)
def pc(x): return x if isinstance(x, str) else ('inf' if x == math.inf else '%.2f%%' % (100 * x))
def pp(x): return '%+.2f' % (100 * x)
VS = [0.2, 0.5, 1.0, 2.0, 5.0]
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}


# ================================================================== K12 report
sha = hashlib.sha256(open(SET_MD, 'rb').read()).hexdigest() if os.path.exists(SET_MD) else 'absent'
P('# K12 output (k12.py)\n')
P('K12_calc-rules.md SHA-256 %s. this document this run before was written(K12_results.md same value recorded).\n' % sha)
P('| input | SHA-256 prior 8 |'); P('|---|---|')
for p_ in [PRICE, SUMCSV, VALCSV, EPOCHS, AGG + '/epochs_busy.csv.gz', G11_L1, G11D + '/G11_gas.md', K11B_OUT, K11D + '/k11b.py', K11D + '/K11b_settings.md', J + '/rule10-candidate/F1_seller-stage-classes.csv']:
    P('| %s | %s |' % (p_.replace(ROOT + '/', ''), sha8(p_)))

PER = ['busy', 'median', 'quiet']
CM = ['N', 'S', 'S-d', 'S-120']
SETL = [('T01t:' + p) for p in PER] + [('T01x:' + p) for p in PER] + ['D94'] + [('old:' + p) for p in PER]

def collect():
    SELL, SETV = {}, {}
    for p in PER:
        for V in (0.2, 1.0):
            for st in ('T01t:' + p, 'BR:' + p):
                g = G(st, V, LOm('N'))
                res = {m: (G(st, V, LOm(m)).opt(W0), G(st, V, UPm(m)).opt(W0), G(st, V, LOm(m, True)).opt(W0)) for m in CM}
                for j, s_ in enumerate(g.S):
                    SELL[(p, V, s_['a'])] = dict(R=s_['R'], n=s_['n'], **{m: (KS[r_[0]['ki'][j]], r_[0]['tot'][j], r_[1]['tot'][j], r_[2]['tot'][j], KS[r_[1]['ki'][j]]) for m, r_ in res.items()})
    for st in SETL:
        for V in (0.2, 1.0):
            for m in CM:
                SETV[(st, V, m)] = (G(st, V, LOm(m)).opt(W0), G(st, V, UPm(m)).opt(W0), G(st, V, LOm(m, True)).opt(W0))
    return SELL, SETV

def vgrid():
    o = {}
    for st in ['T01t:' + p for p in PER] + ['D94'] + ['BR:' + p for p in PER]:
        for m in ('N', 'S'):
            cells = []
            for V in VS:
                lo = G(st, V, LOm(m)).opt(W0); up = G(st, V, UPm(m)).opt(W0)
                cells.append('%s / %s; %s / %s' % (pc(lo['agg']), pc(lo['med']), pc(up['agg']), pc(up['med'])))
            o[(st, m)] = cells
    return o

set_gas('new')

# ---------------- 1. reproduction of K11b with N = 1
P('\n## 1. K11b reproduction: bundle size N = 1 this file k11b_output.md cells as is outputs\n')
SELL, SETV = collect(); VG = vgrid()
kb = open(K11B_OUT, encoding='utf-8').read().split('\n')
def table_rows(lines, header_prefix):
    i = [j for j, l in enumerate(lines) if l.startswith(header_prefix)][0]; rows = []
    for l in lines[i + 1:]:
        if not l.startswith('|'): break
        if not l.startswith('|---'): rows.append([c.strip() for c in l.strip('|').split('|')])
    return rows
def sell_cells(d):
    return ' | '.join('%d | %s | %s | %s' % (d[m][0], pc(d[m][1]), pc(d[m][2]), pc(d[m][3])) for m in ('N', 'S'))
rep_n = {}; rep_bad = []
def rep(group, cell, got, lab):
    a = rep_n.setdefault(group, [0, 0]); a[1] += 1; a[0] += (cell == got)
    if cell != got: rep_bad.append((group, lab, cell, got))
NAME2ST = {sname(st): st for st in SETS_ALL}
WINV = {v: k for k, v in WN.items()}
for row in table_rows(kb, '| window | V | seller | R USDC | n |'):
    p = WINV[row[0]]; V = float(row[1]); d = SELL[(p, V, row[2])]
    for ci, (cell, got) in enumerate(zip(row[5:13], sell_cells(d).split(' | '))): rep('5 (sec.) seller row(N, S: k, lower, upper, lower carry-over)', cell, got, (row[:3], ci))
for row in table_rows(kb, '| set | V | mode | lower pooled / median |'):
    st = NAME2ST[row[0]]
    lo, up, lf = SETV[(st, float(row[1]), row[2])]
    for c, o_ in zip(row[3:6], (lo, up, lf)): rep('5 (sec.) set row(N, S, S-d, S-120: lower, upper, lower carry-over)', c, '%s / %s' % (pc(o_['agg']), pc(o_['med'])), row[:3])
for row in table_rows(kb, '| set | mode | V 0.2 |'):
    st = NAME2ST[row[0]]
    for c, g_ in zip(row[2:7], VG[(st, row[1])]): rep('6 (sec.) V grid', c, g_, row[:2])
P('| Table | cell count | equal |'); P('|---|---|---|')
for k_, (a_, b_) in rep_n.items(): P('| %s | %d | %d |' % (k_, b_, a_))
REP_TOT = (sum(v[1] for v in rep_n.values()), sum(v[0] for v in rep_n.values()))
P('\nN = 1 k11b_output.md %dcell among %dcells as is outputs.' % (REP_TOT[0], REP_TOT[1]))
for b_ in rep_bad[:20]: P('- mismatch: %s' % (b_,))
assert not rep_bad, rep_bad[:3]
print('REPRO', REP_TOT)

# ---------------- 2. bundle constants
P('\n## 2. bundle gas constant (sketch value; G11 in row calculation)\n')
P('| constant | value | basis |'); P('|---|---|---|')
P('| bundle header WRAP (per transaction) | %s gas | bundle P = 1, 32 items %s − self submission 32 items %s (G11 3.1 (sec.)) |' % (fmt(WRAP), fmt(gg(BUN % 1)), fmt(_A32)))
P('| transaction default | 21,000 gas | dividing share. G11 3.1 (sec.) read one 2 |')
P('| scenario S per unit change δ | −21,000 + 24,252 f | f = 1/m (P1) |')
P('| scenario M per unit change (m = 1, 2, 4, 8) | %s | P = 2, 4, 8 transaction gas / P − self submission 32 items (G11 3.1 (sec.)) |' % ', '.join('%+.0f' % y for y in MY))
P('| scenario Z stored compression | −%s gas (N regardless) | 3 × 22,100. rule change required assumption |' % fmt(ZSAVE))
P('| release a (sketch) | %.4f | G11 6 (sec.) caveat 0.6~0.7x interval among m = 8 0.65 |' % REL_A_S)
P('| release a (measured as is) | %.4f | (%s − %s) / 7 = %.1f gas / direct release %s |' % (REL_A_M, fmt(gg(RELB % 8)), fmt(gg(RELB % 1)), REL_MARG, fmt(REL_DIRECT)))
P('| sample value | 1/N (P1) | per set per epoch request %s, accepted %s gas (G11 3.2 (sec.)) |' % (fmt(G_REQ), fmt(G_VRF_EXP)))
P('| transaction gas upper | %s | 2^24 |' % fmt(TX_CAP))

# ---------------- run helpers
SC = {'main': dict(asc='S', peer='P1'), 'measured': dict(asc='M', peer='P1'), 'S,P2': dict(asc='S', peer='P2'), 'Z': dict(asc='Z', peer='P1')}
NS = [1, 4, 16, 64]
SMALL = ['CoinStats(0.01 or less)', 'Exa(0.001 or less)', 'StableApify']
ALL7 = ['StableEnrich(Out candidates excluded)', 'OneSource', 'CoinMarketCap', 'StableApify', 'Exa(0.001 or less)', 'CoinStats(0.01 or less)', 'BlockRun']
def pr(m, up, N, sc):
    f = UPm if up else LOm
    return f(m, bun=N, **SC[sc])
_R = {}
def run(sc, N, m, V, up):
    key = (sc, N, m, V, up)
    if key in _R: return _R[key]
    res = {}
    for p in PER:
        g = G('T01t:' + p, V, pr(m, up, N, sc)); o = g.opt(W0)
        gb = G('BR:' + p, V, pr(m, up, N, sc)); ob = gb.opt(W0)
        tot = {s_['a']: float(o['tot'][j]) for j, s_ in enumerate(g.S)}
        tot['BlockRun'] = float(ob['tot'][0])
        res[p] = dict(tot=tot, agg=o['agg'], med=o['med'], bagg=ob['agg'], g=g, o=o, gb=gb, ob=ob)
    _R[key] = res
    return res

def tab(scn, V, m='N'):
    return {(N, up): run(scn, N, m, V, up) for N in NS for up in (False, True)}

NN = [1, 4, 16, 64]
H1 = '| N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |'
def row_cells(fn, N, T):
    return ' | '.join(fn(T[(N, up)][p]) for p in PER for up in (False, True))

for sc_n, sc in enumerate(['main', 'measured']):
    for V in (1.0, 0.2):
        T = tab(sc, V)
        P('\n## %d. %s scenario(%s) mode N, V %g\n' % (3 + sc_n * 2 + (0 if V == 1.0 else 1), sc, 'anchor S, release a 0.6, concurrent activity P1; bundle gas sketch value' if sc == 'main' else 'anchor M(G11 measured, 8place or less), release a 0.5837; bundle gas G11 see implementation measured', V))
        P('### Table 1. N per median seller cost (T01t seller median, revenue relative to)\n'); P(H1); P('|---|---|---|---|---|---|---|')
        for N in NN: P('| %d | %s |' % (N, row_cells(lambda r: pc(r['med']), N, T)))
        P('\n### Table 2. small seller three cost\n'); P('| seller | N | busy lower | busy upper | median lower | median upper | quiet lower | quiet upper |'); P('|---|---|---|---|---|---|---|---|')
        for nm in SMALL:
            for N in NN: P('| %s | %d | %s |' % (nm, N, row_cells(lambda r: pc(r['tot'][nm]), N, T)))
        P('\n### Table 3. 10% within falling seller count (seven among)\n'); P(H1); P('|---|---|---|---|---|---|---|')
        for N in NN: P('| %d | %s |' % (N, row_cells(lambda r: '%d' % sum(r['tot'][a] <= 0.10 for a in ALL7), N, T)))
        P('\nseven seller whole(lower / upper):\n'); P('| window | seller | ' + ' | '.join('N %d' % N for N in NN) + ' |'); P('|---|---|' + '---|' * len(NN))
        for p in PER:
            for a in ALL7: P('| %s | %s | %s |' % (WN[p], a, ' | '.join('%s / %s' % (pc(T[(N, False)][p]['tot'][a]), pc(T[(N, True)][p]['tot'][a])) for N in NN)))
        P('\n### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)\n'); P('| window | target | N | lower | upper | N = 1 relative to lower change(%p) |'); P('|---|---|---|---|---|---|')
        for p in PER:
            for lab, fn in (('T01t pooled', lambda r, up: r['agg']), ('BlockRun', lambda r, up: r['tot']['BlockRun']), ('StableEnrich(Out candidates excluded)', lambda r, up: r['tot']['StableEnrich(Out candidates excluded)'])):
                for N in NN:
                    lo, up_ = fn(T[(N, False)][p], False), fn(T[(N, True)][p], True); lo1 = fn(T[(1, False)][p], False)
                    P('| %s | %s | %d | %s | %s | %s |' % (WN[p], lab, N, pc(lo), pc(up_), pp(lo - lo1)))

# ---------------- component table (main scenario)
P('\n## 7. Table 4. per component share (main scenario, lower, mode N, V 1; revenue relative to)\n')
P('| window | seller | N | verify | anchor | sampvrf | release | l1 | frozen | deduct | capital | total |'); P('|---|---|---|---|---|---|---|---|---|---|---|---|')
CMP_ROWS = {}
for p in PER:
    for nm in ['T01t median'] + SMALL:
        for N in (1, 64):
            r = run('main', N, 'N', 1.0, False)[p]; g = r['g']
            dd = g.comp(W0)[2]
            if nm.startswith('T01t'):
                ks = np.argsort(dd['total']); jj = [ks[len(ks) // 2 - 1], ks[len(ks) // 2]]       # two middle sellers
                v = {c: float(np.mean([dd[c][j] for j in jj])) for c in dd}
            else:
                j = g.a_.index(nm); v = {c: float(dd[c][j]) for c in dd}
            CMP_ROWS[(p, nm, N)] = v
            P('| %s | %s | %d | %s |' % (WN[p], nm, N, ' | '.join('%.4f' % v[c] for c in ['verify', 'anchor', 'sampvrf', 'release', 'l1', 'frozen', 'deduct', 'capital', 'total'])))
P('\n("T01t median" row seller total middle two seller component is the mean.)')

# ---------------- scenario comparison
P('\n## 8. Table 6. scenario comparison (mode N, V 1): median seller(lower / upper) and 10% within seller count(lower / upper)\n')
P('| scenario | N | busy median | median median | quiet median | 10% within count(busy, median, quiet; lower) | 10% within count(upper) |'); P('|---|---|---|---|---|---|---|')
SCN = []
for sc in ['main', 'measured', 'S,P2', 'Z']:
    for N in NN: SCN.append((sc, N))
SCN += [('main', 4096)]
for sc, N in SCN:
    lo = run(sc, N, 'N', 1.0, False); up = run(sc, N, 'N', 1.0, True)
    P('| %s | %d | %s | %s | %s | %s | %s |' % (sc + (' (limit)' if N == 4096 else ''), N,
        *['%s / %s' % (pc(lo[p]['med']), pc(up[p]['med'])) for p in PER],
        ', '.join('%d' % sum(lo[p]['tot'][a] <= 0.10 for a in ALL7) for p in PER), ', '.join('%d' % sum(up[p]['tot'][a] <= 0.10 for a in ALL7) for p in PER)))
P('\nsmall seller three lower cost(N 64 / limit 4096, main scenario and Z):\n'); P('| window | seller | main N 1 | main N 64 | main N 4096 | Z N 1 | Z N 64 |'); P('|---|---|---|---|---|---|---|')
for p in PER:
    for nm in SMALL:
        P('| %s | %s | %s |' % (WN[p], nm, ' | '.join(pc(run(sc, N, 'N', 1.0, False)[p]['tot'][nm]) for sc, N in (('main', 1), ('main', 64), ('main', 4096), ('Z', 1), ('Z', 64)))))

# ---------------- mode S
P('\n## 9. mode S, V 1, main scenario: median seller(lower / upper) and 10% within seller count(lower)\n')
P('| N | busy | median | quiet | 10% within count(lower) |'); P('|---|---|---|---|---|')
for N in NN:
    lo = run('main', N, 'S', 1.0, False); up = run('main', N, 'S', 1.0, True)
    P('| %d | %s | %s | %s | %s |' % (N, *['%s / %s' % (pc(lo[p]['med']), pc(up[p]['med'])) for p in PER], ', '.join('%d' % sum(lo[p]['tot'][a] <= 0.10 for a in ALL7) for p in PER)))

# ---------------- checks
P('\n## 10. check\n')
fl = [(sc, N, up, p) for sc in ('main', 'measured', 'Z') for N in (4, 16, 64) for up in (False, True) for p in PER if run(sc, N, 'N', 1.0, up)[p]['g'].bund.get('floor_bind')]
P('- EIP-7623 lower bound run gas over cell: %s' % ('none' if not fl else str(fl[:5])))
P('- transaction within unit count m_eff (main scenario, N 64, lower, chosen k): anchor / release')
for p in PER:
    r = run('main', 64, 'N', 1.0, False)[p]; g = r['g']; ki = r['o']['ki']
    P('  - %s: ' % WN[p] + ', '.join('%s %d / %d' % (s_['a'].split('(')[0], g.m_a[ki[j], j], g.m_r[ki[j], j]) for j, s_ in enumerate(g.S)) + '; BlockRun %d / %d' % (r['gb'].m_a[r['ob']['ki'][0], 0], r['gb'].m_r[r['ob']['ki'][0], 0]))
P('- chosen k (main scenario, lower): N 1 vs N 64')
for p in PER:
    r1 = run('main', 1, 'N', 1.0, False)[p]; r64 = run('main', 64, 'N', 1.0, False)[p]
    P('  - %s: ' % WN[p] + ', '.join('%s %d vs %d' % (s_['a'].split('(')[0], KS[r1['o']['ki'][j]], KS[r64['o']['ki'][j]]) for j, s_ in enumerate(r1['g'].S)))
# N=1 equals K11b for the main scenario (not for Z)
for sc in ('main', 'measured', 'S,P2'):
    for p in PER:
        assert abs(run(sc, 1, 'N', 1.0, False)[p]['med'] - SETV[('T01t:' + p, 1.0, 'N')][0]['med']) < 1e-15
P('- N = 1 main, measured, S,P2 scenario median K11b and equal(1e-15 within): check')

# ---------------- 11. inputs of three cells for an independent hand calculation
P('\n## 11. by hand again cell three cell (main scenario, mode N, V 1, lower)\n')
q0 = Prm()
P('constant: 1 gas = %.3f gwei = %.4e USD, 1 L1 wei = %.4e USD. anchor run gas(signature) = %.2f + %.3f x, x = n / A_p (EIP-7623 lower bound not reach not). bundle anchor unit gas = run gas − 21,000 + 24,252 / m (P1). ECVRF sample = (gusd(%s + %s) + wusd(%s + %s)) / N. release gas = Ru × %s × (0.6 + 0.4 / m) + %s n + %s n_s. remaining component(verify, l1, frozen, deduct, capital) K11b appendix and same formula.\n' % (
    q0.gp, q0.gusd(1), 1e-18 * q0.eth, G10B_F[1], G10B_M[1], fmt(G_REQ), fmt(G_VRF_EXP), fmt(W_REQ), fmt(W_VRF), fmt(REL_F['ledger']), fmt(REL_M), fmt(REL_K)))
for p, nm, N in (('quiet', 'Exa(0.001 or less)', 64), ('busy', 'StableApify', 4), ('median', 'CoinStats(0.01 or less)', 16)):
    r = run('main', N, 'N', 1.0, False)[p]; g = r['g']; j = g.a_.index(nm); i = r['o']['ki'][j]
    r1 = run('main', 1, 'N', 1.0, False)[p]; g1 = r1['g']; i1 = r1['o']['ki'][j]
    ag_self = float(np.maximum(G10B_F[1] + G10B_M[1] * (g.n[j] / g.Ap[i, j]), FL_F[1] + FL_M[1] * (g.n[j] / g.Ap[i, j])))
    P('### %s, %s, N %d (N 1: %s)\n' % (WN[p], nm, N, pc(r1['tot'][nm])))
    P('- input: R = %.6f USDC, n = %d, n_s = %.6f, days %d, k = %d, E_p = %d, A_p = %d, x = %.4f, Ru = %d, anchor unit gas(self submission) = %.1f, m_anchor = %d, m_release = %d.' % (
        g.R[j], g.n[j], g.ns[j], g.days, KS[i], g.Ep[i, j], g.Ap[i, j], g.n[j] / g.Ap[i, j], g.Ru[i, j], ag_self, g.m_a[i, j], g.m_r[i, j]))
    P('- bundle anchor unit gas = %.1f (= %.1f − 21,000 + 24,252 / %d)' % (ag_self - 21000 + 24252 / g.m_a[i, j], ag_self, g.m_a[i, j]))
    P('- component(revenue relative to) N %d: ' % N + ', '.join('%s %.6f' % (c, g.c0parts[c][i, j]) for c in g.c0parts) + '; N 1: ' + ', '.join('%s %.6f' % (c, g1.c0parts[c][i1, j]) for c in g1.c0parts))
    frz, ded = g.loss(W0); cp_ = g.cap(0.10)
    P('- frozen %.6f, deduct %.6f, capital %.6f, total %.6f (= %s)\n' % (frz[i, j], ded[i, j], cp_[i, j], r['tot'][nm], pc(r['tot'][nm])))

txt = '\n'.join(out) + '\n'
open(HERE + '/k12_output.md', 'w', encoding='utf-8').write(txt)
print('wrote', HERE + '/k12_output.md', len(out), 'lines')
