"""Concrete cases of the three counterexamples and the three reviewer
points, on the old (c5325ca) and fixed verification contracts, executed by
py-evm (Cancun) on solc-js 0.8.24 builds (via_ir, optimizer 200)."""
import json, sys

# usage: cases.py <dir with art_old/ and art_new/> <synthetic fixture .json>
from eth_abi import encode
from eth_hash.auto import keccak
from eth_keys import keys
import evm

S = sys.argv[1]
fx = json.load(open(sys.argv[2]))
TAG = keccak(b"p5/response/v1")
VA = 1_792_743_000
FEED = 1
key = keys.PrivateKey(keccak(b"g7 concrete feed key"))
SIGNER = int.from_bytes(key.public_key.to_canonical_address(), "big")
L_OLD, L_NEW, S_OLD, S_NEW = (b"\x10" * 19 + bytes([i]) for i in range(4))
r = evm.Runner({
    L_OLD: evm.runtime(f"{S}/art_old", "P5LazerVerifier", [SIGNER, FEED]),
    L_NEW: evm.runtime(f"{S}/art_new", "P5LazerVerifier", [SIGNER, FEED]),
    S_OLD: evm.runtime(f"{S}/art_old", "P5StorageVerifier"),
    S_NEW: evm.runtime(f"{S}/art_new", "P5StorageVerifier"),
})
PSI = keccak(b"g7 case psi")
results = []


def rec(name, got, want):
    results.append((name, got, want, got == want))
    print(f"{'ok  ' if got == want else 'FAIL'} {name}: got {got}, want {want}")


def update(ts, price, channel=3, feed=FEED, k=key):
    payload = (2479346549).to_bytes(4, "big") + ts.to_bytes(8, "big") + bytes([channel, 1]) + feed.to_bytes(4, "big") \
        + bytes([1, 0]) + (price % 2**64).to_bytes(8, "big")
    sig = k.sign_msg_hash(keccak(payload))
    return (706910618).to_bytes(4, "big") + sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v]) \
        + len(payload).to_bytes(2, "big") + payload


def case1a(to, ts, price, channel=3, va=VA, gas=10_000_000):
    m = PSI + update(ts, price, channel)
    ctx = dict(validAfter=va, materialCommit=keccak(m),
               responseHash=keccak(TAG + PSI + encode(["uint32", "int64", "uint64"], [FEED, price, ts])))
    return evm.passes(r, to, ctx, m, gas)


P1, P2 = 189_000_000_000, 191_500_000_000
t0 = VA * 10**6
# (1) V5: first update after validAfter
for tag, to in (("old", L_OLD), ("new", L_NEW)):
    rec(f"1a {tag}: first grid update (ts = validAfter) passes", case1a(to, t0, P1)[0], True)
    rec(f"1a {tag}: later update (validAfter + 30 s) passes", case1a(to, t0 + 30 * 10**6, P2)[0], tag == "old")
    rec(f"1a {tag}: off-grid update (validAfter + 1 us) passes", case1a(to, t0 + 1, P2)[0], tag == "old")
    rec(f"1a {tag}: next grid update (validAfter + 200 ms) passes", case1a(to, t0 + 200_000, P2)[0], tag == "old")
    rec(f"1a {tag}: window edge validAfter + 60 s passes", case1a(to, t0 + 60 * 10**6, P2)[0], tag == "old")
    rec(f"1a {tag}: update on another channel (1) passes", case1a(to, t0, P1, channel=1)[0], tag == "old")
    rec(f"1a {tag}: update before validAfter rejected", case1a(to, t0 - 200_000, P1)[0], False)
# validAfter near 2^64 / 1e6: the old contract overflows (revert), the new one rejects without revert
big = 2**64 // 10**6 + 5
p, _, ok = case1a(L_OLD, 0, P1, va=big)
rec("1a old: validAfter*1e6 overflow reverts", ok, False)
p, _, ok = case1a(L_NEW, 0, P1, va=big)
rec("1a new: validAfter*1e6 beyond uint64 rejected without revert", (p, ok), (False, True))

# gas of the honest call
_, g_old, _ = case1a(L_OLD, t0, P1)
_, g_new, _ = case1a(L_NEW, t0, P1)
print(f"gas verify 1a honest (message execution): old {g_old}, new {g_new}, delta {g_new - g_old}")

# (b) GAS opcode and the call gas: pass only above a threshold, monotone in g
def sweep(to):
    lo, first = None, None
    seq = []
    for g in range(2_000, 40_001, 250):
        seq.append(case1a(to, t0, P1, gas=g)[0])
    first = next((i for i, x in enumerate(seq) if x), None)
    mono = first is not None and all(seq[first:]) and not any(seq[:first])
    return mono, 2_000 + 250 * first if first is not None else None
for tag, to in (("old", L_OLD), ("new", L_NEW)):
    mono, th = sweep(to)
    rec(f"1a {tag}: pass set over call gas 2,000..40,000 is an upper interval", mono, True)
    print(f"   {tag}: lowest passing call gas (step 250): {th}")

# tier 0
H = bytes.fromhex(fx["header"][2:]); BH = bytes.fromhex(fx["BLOCK_HASH"][2:])
AP = [bytes.fromhex(x[2:]) for x in fx["accountProof"]]
B = lambda x: bytes.fromhex(x[2:])


def old_mat(ref, sp):
    return encode(["bytes", "bytes[]", "bytes[]", "uint256", "bytes32"], [H, AP, sp, ref, PSI])


def new_mat(ref, sp, rh, nh):
    return encode(["bytes", "bytes[]", "bytes[]", "uint256", "bytes32", "bytes", "bytes"], [H, AP, sp, ref, PSI, rh, nh])


def t0call(to, m, ref, h, va=VA):
    ctx = dict(validAfter=va, materialCommit=keccak(m), anchoredHash=BH,
               responseHash=keccak(TAG + PSI + encode(["uint256", "bytes32"], [ref, h])))
    return evm.passes(r, to, ctx, m)


T0 = fx["T0"]
ts = lambda b: T0 + 2 * b
N, Z, Lc, E = fx["N"], fx["Z"], fx["L"], fx["E"]
spN, spZ, spE = ([B(x) for x in c["storageProof"]] for c in (N, Z, E))
# (2) W3 leading zero: old format reads the slot of block Z_NEXT = Z.REF + 1 directly
zn = Z["REF"] + 1; zh = B(Z["NEXT_HASH"]); assert zh[0] == 0
m = old_mat(zn, spZ)
rec("0 old: leading-zero hash, honest response passes", t0call(S_OLD, m, zn, zh)[0], False)
rec("0 old: leading-zero hash, shifted (wrong) response passes", t0call(S_OLD, m, zn, zh[1:] + b"\0")[0], True)
m = new_mat(Z["REF"], spZ, B(Z["refHeader"]), B(Z["nextHeader"]))
va = ts(Z["REF"])
rec("0 new: next block hash with leading zero, honest response passes", t0call(S_NEW, m, Z["REF"], B(Z["REF_HASH"]), va)[0], True)
rec("0 new: same, response with the shifted next hash passes", t0call(S_NEW, m, Z["REF"], zh[1:] + b"\0", va)[0], False)
# control: old format with a full-width hash
nn = N["REF"] + 1
rec("0 old: full-width hash, honest passes", t0call(S_OLD, old_mat(nn, spN), nn, B(N["NEXT_HASH"]))[0], True)
# (3) W5 canonical reference block
mN = new_mat(N["REF"], spN, B(N["refHeader"]), B(N["nextHeader"]))
ref, rh = N["REF"], B(N["REF_HASH"])
for va, want in ((ts(ref), True), (ts(ref) + 1, True), (ts(ref + 1) - 1, True), (ts(ref) - 1, False), (ts(ref + 1), False),
                 (0, False), (2**64 - 1, False)):
    rec(f"0 new: ref {ref} with validAfter = ts(ref){va - ts(ref):+d} passes", t0call(S_NEW, mN, ref, rh, va)[0], want)
for va in (0, ts(nn), 2**64 - 1):
    rec(f"0 old: ref {nn} with validAfter {va} passes", t0call(S_OLD, old_mat(nn, spN), nn, B(N["NEXT_HASH"]), va)[0], True)
# wrong next header (not the hash in the ring), wrong ref header
rec("0 new: next header not matching the ring rejected", t0call(S_NEW, new_mat(ref, spN, B(N["refHeader"]), B(Z["nextHeader"])[:-1] + b"\x01"), ref, rh, ts(ref))[0], False)
rec("0 new: ref header not the parent rejected", t0call(S_NEW, new_mat(ref, spN, B(Lc["refHeader"]), B(N["nextHeader"])), ref, rh, ts(ref))[0], False)
rec("0 new: refBlock field not matching headers rejected", t0call(S_NEW, new_mat(ref + 7, spN, B(N["refHeader"]), B(N["nextHeader"])), ref + 7, rh, ts(ref))[0], False)
# last block case: next = anchored block
mL = new_mat(Lc["REF"], [], B(Lc["refHeader"]), B(Lc["nextHeader"]))
rec("0 new: ref = NUM - 1 (next is the anchored block) passes", t0call(S_NEW, mL, Lc["REF"], B(Lc["REF_HASH"]), ts(Lc["REF"]))[0], True)
# (c) empty slot
en = E["NEXT"]
p, _, ok = t0call(S_OLD, old_mat(en, spE), en, b"\0" * 32)
rec("0 old: absent slot, response 0 -> (pass, call success)", (p, ok), (False, False))
p, _, ok = t0call(S_NEW, new_mat(en - 1, spE, B(N["refHeader"]), B(N["nextHeader"])), en - 1, b"\0" * 32, ts(en - 1))
rec("0 new: absent slot -> (pass, call success)", (p, ok), (False, False))
_, g0o, _ = t0call(S_OLD, old_mat(nn, spN), nn, B(N["NEXT_HASH"]))
_, g0n, _ = t0call(S_NEW, mN, ref, rh, ts(ref))
print(f"gas verify 0 honest (message execution, synthetic fixture): old {g0o}, new {g0n}, delta {g0n - g0o}")
cd = lambda b: sum(16 if x else 4 for x in b)
mo = old_mat(nn, spN)
print(f"material 0: bytes old {len(mo)}, new {len(mN)}; calldata gas (16/4) old {cd(mo)}, new {cd(mN)}, delta {cd(mN) - cd(mo)}")
bad = [x for x in results if not x[3]]
print(f"{len(results) - len(bad)} of {len(results)} as expected")
