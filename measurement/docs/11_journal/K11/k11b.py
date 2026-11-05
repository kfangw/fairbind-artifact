#!/usr/bin/env python3
"""K11b: k11.py with the gas constants of the events measured in G11 (G11_gas.md incl. sec. 6 caveat) replacing the sketch
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
SET_MD = HERE + '/K11b_settings.md'
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
K11_OUT = HERE + '/k11_output.md'
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
                 fpe=True, df1=True, e2935=True, curpe=True, bV=True, DA=120, SV=31, TP=TP0, TC=TC0, t0rs=False)
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
        self.S = S; self.N = len(S); self.Wb = self.days * 43200; Nep = self.days * 144
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
        parts['anchor'] = prm.gusd(A * ag) / R
        parts['sampvrf'] = Ep * prm.rand_usd() / R                                   # randomness incl. its L1 (K10d kept that L1 in 'l1')
        if prm.up and prm.curpe:                         # K10h (d): upper case, release fixed cost per active profile epoch
            Ru = np.broadcast_to((E[0] + self.Ur[0])[None, :], E.shape).copy()
        else:
            Ru = E + self.Ur
        self.Ru = Ru
        parts['release'] = prm.gusd(Ru * REL_F[prm.rd] + REL_M * n[None, :] + REL_K * ns[None, :]) / R
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

sha = hashlib.sha256(open(SET_MD, 'rb').read()).hexdigest() if os.path.exists(SET_MD) else 'absent'
P('# K11b output (k11b.py)\n')
P('K11b_settings.md SHA-256 %s. settings this run before were fixed(K11b_results.md same value recorded).\n' % sha)
P('| input | SHA-256 prior 8 |'); P('|---|---|')
F1CSV = J + '/rule10-candidate/F1_seller-stage-classes.csv'
for p_ in [PRICE, SUMCSV, VALCSV, OBS1, OBS02, MEMB, EPOCHS, AGG + '/epochs_busy.csv.gz', G10B_L1, G10C_L1, G10C_SUM, G10C_BIG, G10D_VRF, G10D_MD, G11_L1, G11D + '/G11_gas.md', K11_OUT, HERE + '/k11.py', F1CSV, K10D + '/k10h.py', K10D + '/k10h_output.md']:
    P('| %s | %s |' % (p_.replace(ROOT + '/', ''), sha8(p_)))
P('\nR10 list: %s. per epoch sales count epochs_{busy,median}.csv.gz(600 s epoch), partial seller E1 k10h_output.md 2 (sec.) value %s.' % (
    'none' if all(LINFO.get(w) == 'missing' for w in ('busy', 'median')) else 'present', ', '.join('%s %s %d' % (WN[a], b, c) for (a, b), c in PART_E1.items())))


# ================================================================== K11b report
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


def wstars():
    o = {}
    for st in ['T01t:' + p for p in PER] + ['D94'] + ['BR:' + p for p in PER]:
        for wh in ('agg', 'med'):
            if st.startswith('BR') and wh == 'med': continue
            for m in ('N', 'S'):
                for V in (0.2, 1.0):
                    o[(st, wh, m, V)] = (G(st, V, LOm(m)).wstar(wh), G(st, V, UPm(m)).wstar(wh))
    return o


def optrows():
    OPT = {}
    for p in PER:
        for st in ('T01t:' + p, 'BR:' + p):
            g0 = G(st, 1.0, LOm('N'))
            for j, s_ in enumerate(g0.S):
                for lab, f in (('lower', LOm), ('upper', UPm)):
                    for m in ('N', 'S'):
                        best = None
                        for V in VS:
                            g = G(st, V, f(m)); t = g.total(W0)[:, j]; i = int(np.argmin(t)); c = (t[i], V, KS[i], g)
                            if best is None or c[0] < best[0] - 1e-15: best = c
                        tot, V, k, g = best
                        hold = s_['R'] / g.Wb * g.prm.H(k)
                        t1 = G(st, 1.0, f(m)).total(W0)[KS.index(k), j]
                        OPT[(p, s_['a'], lab, m)] = (V, k, tot, g.b, hold, g.b + hold, t1, s_['R'], g.days)
    SOPT = {}
    for st in ['T01t:' + p for p in PER] + ['D94']:
        for m in ('N', 'S'):
            best = None
            for V in VS:
                g = G(st, V, LOm(m)); o = g.opt(W0)
                if best is None or o['agg'] < best[0] - 1e-15: best = (o['agg'], V, g, o)
            a_, V, g, o = best
            Hs = np.array([g.prm.H(KS[i]) for i in o['ki']]); hold = (g.R / g.Wb * Hs).sum(); sb = g.b * g.N
            SOPT[(st, m)] = (a_, V, o['med'], sb, hold, g.R.sum())
    return OPT, SOPT


CN = ['verify', 'anchor', 'sampvrf', 'release', 'l1', 'detincl', 'failpath', 'frozen', 'deduct', 'capital', 'total']
def comps():
    o = {}
    for st in ['T01t:' + p for p in PER] + ['D94'] + ['BR:' + p for p in PER]:
        for V in (0.2, 1.0):
            for lab, f in (('lower', LOm), ('upper', UPm)):
                for m in ('N', 'S'):
                    d, _, _ = G(st, V, f(m)).comp(W0)
                    o[(st, V, lab, m)] = d
    return o


# ---------------- old gas (= K11) block
set_gas('old')
SELL_O, SETV_O = collect(); VG_O = vgrid(); WS_O = wstars(); OPT_O, SOPT_O = optrows(); CMP_O = comps()
UA_O = {st: float(G(st, 1.0, LOm('N')).Ua[0].sum()) for st in ('T01t:busy', 'T01t:median', 'T01t:quiet', 'D94', 'BR:busy', 'BR:median', 'BR:quiet')}

# ---------------- 1. reproduction of K11 with the K11 gas constants
P('\n## 1. K11 reproduction: old gas(set_gas("old")) put in this file k11_output.md cells as is outputs\n')
ko = open(K11_OUT, encoding='utf-8').read().split('\n')
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
for row in table_rows(ko, '| window | V | seller | R USDC | n |'):
    p = {v: k for k, v in WN.items()}[row[0]]; V = float(row[1])
    d = SELL_O[(p, V, row[2])]
    rep('4 (sec.) seller row(N, S: k, lower, upper, lower carry-over)', ' | '.join(row[5:13]), sell_cells(d), row[:3])
for row in table_rows(ko, '| set | V | mode | lower pooled / median |'):
    if row[2] not in CM: continue
    st = NAME2ST[row[0]]
    if (st, float(row[1]), row[2]) not in SETV_O: continue
    lo, up, lf = SETV_O[(st, float(row[1]), row[2])]
    for c, o_ in zip(row[3:6], (lo, up, lf)): rep('4 (sec.) set row(N, S, S-d, S-120)', c, '%s / %s' % (pc(o_['agg']), pc(o_['med'])), row[:3])
for row in table_rows(ko, '| set | mode | V 0.2 |'):
    st = NAME2ST[row[0]]
    for c, g_ in zip(row[2:7], VG_O[(st, row[1])]): rep('5 (sec.) V grid', c, g_, row[:2])
P('| Table | cell count | equal |'); P('|---|---|---|')
for k_, (a_, b_) in rep_n.items(): P('| %s | %d | %d |' % (k_, b_, a_))
P('\nold gas k11_output.md %dcell among %dcells as is outputs.' % (sum(v[1] for v in rep_n.values()), sum(v[0] for v in rep_n.values())))
for b_ in rep_bad[:20]: P('- mismatch: %s' % (b_,))
assert not rep_bad, rep_bad[:3]

# ---------------- new gas
set_gas('new')
SELL, SETV = collect(); VG = vgrid(); WS = wstars(); OPT, SOPT = optrows(); CMP = comps()

P('\n## 2. changed gas constant (old value K11, new value K11b)\n')
P('| constant | old value | new value | new value / old value |'); P('|---|---|---|---|')
def crow(nm, o, n_): P('| %s | %s | %s | %.3f |' % (nm, ('%s' % format(o, ',.1f') if o != int(o) else format(int(o), ',')), ('%s' % format(n_, ',.1f') if n_ != int(n_) else format(int(n_), ',')), n_ / o))
for s_, tx in ((1, 'signature'), (0, 'signature none')):
    crow('anchor per sale gas, %s' % tx, OLDG['G10B_M'][s_], G10B_M[s_])
    crow('anchor fixed gas, %s' % tx, OLDG['G10B_F'][s_], G10B_F[s_])
    crow('EIP-7623 lower slope, %s' % tx, OLDG['FL_M'][s_], FL_M[s_])
    crow('EIP-7623 lower intercept, %s' % tx, OLDG['FL_F'][s_], FL_F[s_])
crow('sample request ECVRF (G_REQ)', OLDG['G_REQ'], G_REQ); crow('sample value accepted ECVRF (G_VRF_EXP)', OLDG['G_VRF_EXP'], G_VRF_EXP)
crow('sample request Chainlink (CL_REQ)', OLDG['CL_REQ'], CL_REQ)
crow('proof call tier 1a (RS3 cell)', OLDG['CPG']['RS3'][0], CPG['RS3'][0]); crow('proof call tier 0', OLDG['CPG']['SP0'][0], CPG['SP0'][0])
crow('proof call tier 0 upper (SP0_UP)', OLDG['SP0_UP'], SP0_UP)
crow('dispute open (G_OPEN)', OLDG['G_OPEN'], G_OPEN); crow('decryption dispute 4 KB (G_DEC)', OLDG['G_DEC'], G_DEC)
P('\nnot changing not one: bundled release and direct release(REL_F %s, REL_M %s, REL_K %s), proof call tier 1b(TEE %s), settlement gas, failure path %s, Chainlink fulfillment %s, transaction capacity CAP_GAS %s, L1 wei all, upper margin %s + per level %s.\n' % (
    fmt(REL_F['ledger']), fmt(REL_M), fmt(REL_K), fmt(CPG['TEE'][0]), fmt(G_FAIL), fmt(CL_BILL), CAP_GAS, fmt(G_DET), fmt(G_LVL)))

# ---------------- 2. modes
P('\n## 3. mode parameters and retention, freeze interval (block, 2 s)\n')
P('| mode | b | a_A | τ_V + 1 + T_V | T_p | T_c | H(1) | H(32) | Δ_f | H(1) time | Δ_f time | OneSource proof |'); P('|---|---|---|---|---|---|---|---|---|---|---|---|')
for m in ('OLD', 'N', 'S', 'S-d', 'S-120'):
    q_ = PD(1.0, **MODES[m])
    P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %.2f | %.2f | %s |' % (m, 'V' if q_.bV else 'bond(V) = V/0.675', fmt(q_.DA), fmt(q_.SV), fmt(q_.TP), fmt(q_.TC), fmt(q_.H(1)), fmt(q_.H(32)), fmt(q_.DF(1)),
      q_.H(1) * 2 / 3600, q_.DF(1) * 2 / 3600, 'RS3(signature feed kept)' if q_.t0rs else ('SP0' if EPB + q_.DA <= EIP2935_OK else 'SP0 impossible')))

# ---------------- 3. admission checks
P('\n## 4. admission inspection (19) and related inspection (value: left side vs right side)\n')
def chk(m):
    c = CH[m]; d, ma, aF, aA = c['d_inc'], c['m_a'], c['a_F'], c['a_A']
    r = []
    r.append(('(19) m_a ≥ d_inc', '%s ≥ %s' % (fmt(ma), fmt(d)), ma >= d))
    r.append(('(19) a_A ≥ d_inc + m_a (registration when)', '%s ≥ %s' % (fmt(aA), fmt(d + ma)), aA >= d + ma))
    if aF is None:
        r.append(('(19) a_F ≥ d_inc + m_a (joining when)', 'set none(applicable none)', None))
        r.append(('(19) a_A − a_F ≥ d_inc + m_a (joining when)', 'set none(applicable none)', None))
    else:
        r.append(('(19) a_F ≥ d_inc + m_a (joining when)', '%s ≥ %s' % (fmt(aF), fmt(d + ma)), aF >= d + ma))
        r.append(('(19) a_A − a_F ≥ d_inc + m_a (joining when)', '%s ≥ %s' % (fmt(aA - aF), fmt(d + ma)), aA - aF >= d + ma))
    r.append(('(19) 100 ≤ a_A ≤ 150', '%s' % fmt(aA), 100 <= aA <= 150))
    r.append(('(1) T_epoch ≥ τ_V + 1 + T_V', '300 ≥ %s' % fmt(c['SV']), 300 >= c['SV']))
    r.append(('(1) a_A < T_epoch', '%s < 300' % fmt(aA), aA < 300))
    r.append(('(3) w_b ≥ 1 + d_inc', '%s ≥ %s' % (fmt(c['w_b']), fmt(1 + d)), c['w_b'] >= 1 + d))
    r.append(('(5) tier 0: 300 + a_A ≤ 8,191 − margin(8,000)', '%s ≤ 8,000' % fmt(300 + aA), 300 + aA <= 8000))
    r.append(('(11) T_rs ≤ T_c − d_inc', '%s ≤ %s' % (fmt(c['T_rs']), fmt(c['TC'] - d)), c['T_rs'] <= c['TC'] - d))
    r.append(('(15) T_x ≥ d_inc', '%s ≥ %s' % (fmt(c['T_x']), fmt(d)), c['T_x'] >= d))
    r.append(('(16) tier 1a: 2 × a_A seconds ≥ δ_sig + update spacing', 'left side %s s(right side value none)' % fmt(2 * aA), None))
    return r
P('| inspection | ' + ' | '.join(CH) + ' |'); P('|---|' + '---|' * len(CH))
CHK = {m: chk(m) for m in CH}
for i in range(len(CHK['N'])):
    P('| %s | %s |' % (CHK['N'][i][0], ' | '.join('%s: %s' % (x[i][1], {True: 'holds', False: 'does not hold not', None: '-'}[x[i][2]]) for x in CHK.values())))
P('\nverdict 1 (19):')
for m, rr in CHK.items():
    f19 = [x for x in rr if x[0].startswith('(19)') and x[2] is False]
    ineq = [x for x in f19 if '100' not in x[0]]
    v = 'pass' if not f19 else ('inequality holds, range fails' if not ineq else 'fails(%s)' % ', '.join(x[0][5:] for x in f19))
    P('- %s: %s' % (m, v))


# ---------------- 5. per-seller totals (new gas)
P('\n## 5. per seller and set total (K11b; revenue relative to %%; σ 1, w %g, r 10%%, a 0, per seller optimal k)\n' % W0)
MS = ['N', 'S']
P('| window | V | seller | R USDC | n | ' + ' | '.join('%s k | %s lower | %s upper | %s lower carry-over' % (m, m, m, m) for m in MS) + ' |'); P('|---|---|---|---|---|' + '---|' * (4 * len(MS)))
for (p, V, a), d in SELL.items():
    P('| %s | %g | %s | %.2f | %d | %s |' % (WN[p], V, a, d['R'], d['n'], sell_cells(d)))
P('\nset pooled / median (lower; upper; lower carry-over):\n')
P('| set | V | mode | lower pooled / median | upper pooled / median | lower carry-over pooled / median |'); P('|---|---|---|---|---|---|')
for st in SETL:
    for V in (0.2, 1.0):
        for m in CM:
            lo, up, lf = SETV[(st, V, m)]
            P('| %s | %g | %s | %s / %s | %s / %s | %s / %s |' % (sname(st), V, m, pc(lo['agg']), pc(lo['med']), pc(up['agg']), pc(up['med']), pc(lf['agg']), pc(lf['med'])))
P('\nS OneSource without T01t(sensitivity; lower pooled / median):\n')
P('| window | V | S lower | S upper | N lower(same set) |'); P('|---|---|---|---|---|')
for p in PER:
    for V in (0.2, 1.0):
        out_ = []
        for m, f in (('S', LOm), ('S', UPm), ('N', LOm)):
            g = G('T01t:' + p, V, f(m)); o = g.opt(W0); msk = np.array([a != 'OneSource' for a in g.a_]); t = o['tot'][msk]; R_ = g.R[msk]
            out_.append('%s / %s' % (pc(float((t * R_).sum() / R_.sum())), pc(float(np.median(t)))))
        P('| %s | %g | %s |' % (WN[p], V, ' | '.join(out_)))

P('\n## 6. V grid set total (lower pooled / median; upper pooled / median)\n')
P('| set | mode | ' + ' | '.join('V %g' % V for V in VS) + ' |'); P('|---|---|' + '---|' * len(VS))
for (st, m), cells in VG.items(): P('| %s | %s | %s |' % (sname(st), m, ' | '.join(cells)))

P('\n## 7. cost optimum (V, k) and retention payment (σ 1, w %g, facilitator none; K11 columns same point old gas value)\n' % W0)
P('| window | seller | case | mode | V* | k* | total | K11 V* | K11 k* | K11 total | same k V 1 total | b | R/W_b × H(k*) | L USDC | L / R | L days |'); P('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for (p, a, lab, m), (V, k, tot, b, hold, L, t1, Rr, days) in OPT.items():
    o = OPT_O[(p, a, lab, m)]
    P('| %s | %s | %s | %s | %g%s | %d | %s | %g | %d | %s | %s | %.2f | %.4f | %.4f | %s | %.2f |' % (WN[p], a, lab, m, V, ' (grid end)' if V in (0.2, 5.0) else '', k, pc(tot), o[0], o[1], pc(o[2]), pc(t1), b, hold, L, pc(L / Rr), L / (Rr / days)))
P('\nset optimal V (all seller same V, per seller k; lower pooled min) and retention payment sum:\n')
P('| set | mode | V* | lower pooled | median | Σb | Σ R/W_b H(k) | ΣL USDC | ΣL / ΣR | K11 V* | K11 pooled |'); P('|---|---|---|---|---|---|---|---|---|---|---|')
for (st, m), (a_, V, med, sb, hold, Rs) in SOPT.items():
    o = SOPT_O[(st, m)]
    P('| %s | %s | %g | %s | %s | %.2f | %.2f | %.2f | %s | %g | %s |' % (sname(st), m, V, pc(a_), pc(med), sb, hold, sb + hold, pc((sb + hold) / Rs), o[1], pc(o[0])))

# ---------------- 8. differences K11b - K11
P('\n## 8. K11 relative to difference (K11b − K11, %p; facilitator none)\n')
P('| window | V | seller | case | mode | K11 | K11b | difference | K11 k | K11b k |'); P('|---|---|---|---|---|---|---|---|---|---|')
for (p, V, a), d in SELL.items():
    for lab, ix, kx in (('lower', 1, 0), ('upper', 2, 4)):
        for m in MS:
            o = SELL_O[(p, V, a)][m]
            P('| %s | %g | %s | %s | %s | %s | %s | %s | %d | %d |' % (WN[p], V, a, lab, m, pc(o[ix]), pc(d[m][ix]), pp(d[m][ix] - o[ix]), o[kx], d[m][kx]))
P('\nset (pooled / median):\n')
P('| set | V | case | mode | K11 | K11b | pooled difference | median difference |'); P('|---|---|---|---|---|---|---|---|')
for st in SETL:
    for V in (0.2, 1.0):
        for lab, ix in (('lower', 0), ('upper', 1)):
            for m in CM:
                o, n_ = SETV_O[(st, V, m)][ix], SETV[(st, V, m)][ix]
                P('| %s | %g | %s | %s | %s / %s | %s / %s | %s | %s |' % (sname(st), V, lab, m, pc(o['agg']), pc(o['med']), pc(n_['agg']), pc(n_['med']), pp(n_['agg'] - o['agg']), pp(n_['med'] - o['med'])))

P('\n## 9. 10% threshold w* (σ 1, facilitator none; lower / upper; K11 → K11b "K11 | K11b" column)\n')
P('| set | statistics | mode | V | K11 | K11b |'); P('|---|---|---|---|---|---|')
for (st, wh, m, V), (lo, up) in WS.items():
    o = WS_O[(st, wh, m, V)]
    P('| %s | %s | %s | %g | %s / %s | %s / %s |' % (sname(st), {'agg': 'pooled', 'med': 'median'}[wh], m, V, g3(o[0]), g3(o[1]), g3(lo), g3(up)))

P('\n## 10. verdict 2 (T01t pooled ≤ 10%, facilitator none, V 0.2 and 1, lower and upper)\n')
P('| edition | mode | case | V | busy | median | quiet | verdict |'); P('|---|---|---|---|---|---|---|---|')
JUDGE = {}
for tag, SV in (('K11', SETV_O), ('K11b', SETV)):
    for m in ('N', 'S'):
        for lab, ix in (('lower', 0), ('upper', 1)):
            for V in (0.2, 1.0):
                xs = [SV[('T01t:' + p, V, m)][ix]['agg'] for p in PER]
                ok = sum(x <= 0.10 for x in xs); v = {3: 'holds', 0: 'does not hold not'}.get(ok, 'partial')
                JUDGE[(tag, m, lab, V)] = v
                P('| %s | %s | %s | %g | %s | %s |' % (tag, m, lab, V, ' | '.join(pc(x) for x in xs), v))

# ---------------- 11. D2
P('\n## 11. p_max floor 1 gwei (D2): signature client preliminary (dispute gas only new value, L1 wei K11 and equal)\n')
ETHB = BASIS['g10b'][1]
def reserve(pg): return (G_OPEN + G_DEC) * pg * 1e-9 * ETHB + (W_OPEN + W_DEC) * 1e-18 * ETHB
P('dispute open 1 KB %s gas(K11 %s), decryption dispute 4 KB %s gas(K11 %s). open purchase one preliminary: p_max 1 gwei %.6f USD(K11 %.6f), 0.0161 gwei %.6f USD.\n' % (
    fmt(G_OPEN), fmt(OLDG['G_OPEN']), fmt(G_DEC), fmt(OLDG['G_DEC']), reserve(1.0), (OLDG['G_OPEN'] + OLDG['G_DEC']) * 1e-9 * ETHB + (W_OPEN + W_DEC) * 1e-18 * ETHB, reserve(0.0161)))

# ---------------- 12. components
P('\n## 12. component (pooled; K11b / K11)\n')
P('| set | V | case | mode | ' + ' | '.join(CN) + ' |'); P('|---|---|---|---|' + '---|' * len(CN))
for (st, V, lab, m), d in CMP.items():
    o = CMP_O[(st, V, lab, m)]
    P('| %s | %g | %s | %s | %s |' % (sname(st), V, lab, m, ' | '.join(('%s / %s' % (f4(d[c][0]), f4(o[c][0]))) if c in d else '-' for c in CN)))

# ---------------- 13. sensitivities
P('\n## 13. sensitivity L, W, U, C (for verdicts not used not; pooled, lower / upper)\n')
P('anchor transaction capacity: K11 CAP_GAS %s, C %s. capacity reaching added unit arising seller added unit sum(V 1, N): K11 %s.\n' % (OLDG['CAP_GAS'], new_values(cap=True)['CAP_GAS'], {k_: v_ for k_, v_ in UA_O.items()}))
P('| set | V | mode | K11 | K11b | L | W | U | C |'); P('|---|---|---|---|---|---|---|---|---|')
SENS_ST = ['T01t:' + p for p in PER] + ['BR:' + p for p in PER] + ['D94']
SV_ = {}
for nm in ('new', 'L', 'W', 'U', 'C', 'old'):
    set_gas(nm)
    for st in SENS_ST:
        for V in (0.2, 1.0):
            for m in ('N', 'S'):
                SV_[(nm, st, V, m)] = (G(st, V, LOm(m)).opt(W0)['agg'], G(st, V, UPm(m)).opt(W0)['agg'], float(G(st, V, LOm(m)).Ua[0].sum()))
for st in SENS_ST:
    for V in (0.2, 1.0):
        for m in ('N', 'S'):
            P('| %s | %g | %s | %s |' % (sname(st), V, m, ' | '.join('%s / %s' % (pc(SV_[(nm, st, V, m)][0]), pc(SV_[(nm, st, V, m)][1])) for nm in ('old', 'new', 'L', 'W', 'U', 'C'))))
P('\nC added anchor unit arising set(V 1, N, added unit sum): ' + ', '.join('%s %.0f' % (st, SV_[('C', st, 1.0, 'N')][2]) for st in SENS_ST) + '. K11b: ' + ', '.join('%s %.0f' % (st, SV_[('new', st, 1.0, 'N')][2]) for st in SENS_ST) + '.')
set_gas('new')

# ---------------- 14. appendix cells
P('\n## 14. independent for checking three cell (rule: T01t and BlockRun, V 1, lower, mode N |K11b − K11| max cell, seller mutually differs)\n')
cand = sorted(((abs(d['N'][1] - SELL_O[k_]['N'][1]), k_) for k_, d in SELL.items() if k_[1] == 1.0), reverse=True)
CELLS = []; seen = set()
for dv, (p, V, a) in cand:
    if a in seen: continue
    seen.add(a); CELLS.append((('BR:' if a == 'BlockRun' else 'T01t:') + p, V, a, 'lower', 'N', dv))
    if len(CELLS) == 3: break
q0 = Prm()
P('constant: 1 gas = gp × 1e-9 × ETH USD, gp = %.3f gwei, ETH %.2f. 1 wei(L1) = 1e-18 × ETH USD. anchor(σ 1) run gas = %.2f + %.3f x, EIP-7623 lower gas = %.2f + %.3f x, two among large value(x = n / A_p). anchor L1 wei = A_p × %.4f + n × %.4f. release gas = Ru × %s + %s n + %s n_s, release L1 wei = Ru × %.4f + n × %.4f. ECVRF sample = gusd(%s + %s) + wusd(%s + %s).\n' % (
    q0.gp, q0.eth, G10B_F[1], G10B_M[1], FL_F[1], FL_M[1], L1W_F[1], L1W_M[1], fmt(REL_F['ledger']), fmt(REL_M), fmt(REL_K), RW_F, RW_M, fmt(G_REQ), fmt(G_VRF_EXP), fmt(W_REQ), fmt(W_VRF)))
P('proof price: RS3 = gusd(%s) + wusd(%s) = %.8f USD (K11 %.8f). TEE = gusd(%s) + wusd(%s) = %.8f USD. SP0(lower) = gusd(%s) + wusd(%s) + gusd(%s) = %.8f USD.\n' % (
    fmt(CPG['RS3'][0]), fmt(CPG['RS3'][1]), q0.cpu('RS3'), (OLDG['CPG']['RS3'][0] * q0.gp * 1e-9 * q0.eth + q0.wusd(OLDG['CPG']['RS3'][1])), fmt(CPG['TEE'][0]), fmt(CPG['TEE'][1]), q0.cpu('TEE'), fmt(CPG['SP0'][0]), fmt(CPG['SP0'][1]), fmt(G_BH_READ), q0.cpu('SP0')))
for st, V, nm, lab, m, dv in CELLS:
    pr = (LOm if lab == 'lower' else UPm)(m); g = G(st, V, pr); j = g.a_.index(nm); o = g.opt(W0); i = o['ki'][j]
    frz, ded = g.loss(W0); cp_ = g.cap(0.10)
    P('### %s, %s, V %g, %s, mode %s (K11b − K11 = %+.2f%%p)\n' % (WN[st.split(':')[1]], nm, V, lab, m, 100 * dv * (1 if True else 0)))
    P('- input: R = %.6f USDC, n = %d, n_s = %.6f, days %d, E_p = %d, A_p = %d, chosen k = %d, Ru = %d, proof %s c_P = %.8f USD, b = %.6f, H(k) = %s, Δ_f = %s, w = %g, r 0.10, a 0.' % (
        g.R[j], g.n[j], g.ns[j], g.days, g.Ep[i, j], g.Ap[i, j], KS[i], g.Ru[i, j], g.ck[j], g.cp[j], g.b, fmt(g.Hk[i, 0]), fmt(g.DFk[i, 0]), W0))
    P('- component(revenue relative to): ' + ', '.join('%s %.6f' % (c, g.c0parts[c][i, j]) for c in g.c0parts) + ', frozen %.6f, deduct %.6f, capital %.6f, total %.6f (= %s)' % (frz[i, j], ded[i, j], cp_[i, j], o['tot'][j], pc(o['tot'][j])))
    P('- other k total: ' + ', '.join('k %d %.6f' % (KS[ii], g.total(W0)[ii, j]) for ii in range(len(KS))) + '\n')
print('CELLS', [(c[0], c[2]) for c in CELLS])

txt = '\n'.join(out) + '\n'
open(HERE + '/k11b_output.md', 'w').write(txt)
print('wrote', HERE + '/k11b_output.md', len(out), 'lines')
