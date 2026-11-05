#!/usr/bin/env python3
"""WF1 measurement: availability gaps of signed price feeds on Base.

Registered in WF1_registration.md. Standard library only; HTTP goes through the curl binary.

Subcommands
  plan                      print window, boundary count, block ranges, call estimate
  fetch   [--raw DIR]       append new on-chain events for every registered feed up to the safe head
  analyze [--raw DIR]       compute the registered statistics and verdict sentences
  verify  [--raw DIR]       independent state-read cross-check on a seeded boundary sample
  pilot   [--start ISO] [--n N] [--raw DIR]
                            fetch + analyze a small window (default 20 boundaries before the registered window);
                            the output is a functional test, not a result

The registered window is [WINDOW_START, WINDOW_START + N_BOUNDARIES * 300 s). A boundary is a failure
for feed f when the gap (prev, next] that contains it is longer than G_f seconds.
"""
import argparse, bisect, datetime as dt, json, math, os, random, subprocess, sys, time
from collections import Counter

# ---------------------------------------------------------------- registered constants
WINDOW_START = int(dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc).timestamp())
N_BOUNDARIES = 13824          # 48 days of 5-minute boundaries, backward window ending 2026-10-27 00:00 UTC
PAD = 600                     # look-back and look-ahead beyond G, seconds
STEP = 300
TOL = 0.0025                  # predicate tolerance (descriptive indicator only)
BAND_LO, BAND_HI = 0.002, 0.01
OLD_THRESHOLD = 0.0015
ALPHA = 0.05
SAFE_BLOCKS = 100             # stay this many blocks behind the head (about 200 s)
SPAN = 50000                  # blocks per eth_getLogs call (publicnode limit)
VERIFY_SAMPLE = 60            # boundaries per feed per `verify` run (state reads only work for recent blocks)
VERIFY_DEPTH = 45 * 86400     # sample only boundaries newer than this, inside the free archive depth
VERIFY_SEED = 20261029

ENDPOINTS = ["https://base-rpc.publicnode.com", "https://mainnet.base.org"]

T_CL_ANSWER = "0x0559884fd3a460db3073b7fc896cc77986f16e378210ded43186175bf646fc5f"   # AnswerUpdated(int256,uint256,uint256)
T_A3_SET = "0xb7712be6248d021e8c56ac9613c09491354a4d0f4ad0b7db1a664b35be4b2349"      # UpdatedBeaconSetWithBeacons(bytes32,int224,uint32)
A3_SERVER = "0x709944a48cAf83535e43471680fDA4905FB3920a"
SEL = {"aggregator()": "0x245a7bfc", "phaseId()": "0x58303b10", "latestRoundData()": "0xfeaf968c",
       "dapiNameToDataFeedId(bytes32)": None, "dataFeeds(bytes32)": None}

# G: declared bound on the interval between two consecutive updates (heartbeat plus grace), seconds.
FEEDS = [
    dict(id="CL-BTCUSD", provider="Chainlink", kind="chainlink", proxy="0x64c911996D3c6aC71f9b455B1E8E7266BcbD848F",
         G=1200 + 60, declared="heartbeat 1200 s, deviation 0.1% (Chainlink docs page, read 2026-10-29)"),
    dict(id="CL-ETHUSD", provider="Chainlink", kind="chainlink", proxy="0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70",
         G=1200 + 60, declared="heartbeat 1200 s, deviation 0.15% (Chainlink docs page, read 2026-10-29)"),
    dict(id="A3-BTCUSD", provider="API3", kind="api3", dapi="BTC/USD",
         G=86400 + 3600, declared="heartbeat 86400 s assumed; NOT verified (see WF1_registration.md 3.3)"),
    dict(id="A3-ETHUSD", provider="API3", kind="api3", dapi="ETH/USD",
         G=86400 + 3600, declared="heartbeat 86400 s assumed; NOT verified (see WF1_registration.md 3.3)"),
]

# ---------------------------------------------------------------- keccak (only for two selectors)
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def keccak256(data):
    rate = 136
    p = bytearray(data); p.append(0x01)
    while len(p) % rate:
        p.append(0)
    p[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(p), rate):
        blk = p[off:off + rate]
        for i in range(rate // 8):
            A[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        for rc in _RC:
            C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
            D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
            A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
            B = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _ROT[x][y])
            A = [[B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            A[0][0] ^= rc
    return b"".join(A[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


def selector(sig):
    return "0x" + keccak256(sig.encode())[:4].hex()


# ---------------------------------------------------------------- RPC with ledger
class Rpc:
    def __init__(self, ledger_path=None):
        self.ledger = Counter()
        self.ledger_path = ledger_path
        self.ep = 0
        self.last = 0.0

    def save(self):
        if self.ledger_path:
            old = {}
            if os.path.exists(self.ledger_path):
                old = json.load(open(self.ledger_path))
            for k, v in self.ledger.items():
                old[k] = old.get(k, 0) + v
            json.dump(old, open(self.ledger_path, "w"), indent=1, sort_keys=True)
            self.ledger = Counter()

    def call(self, method, params, tries=6):
        """Return (result, error_class). error_class in {None,'range','rpc','http','timeout'}."""
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        err = "http"
        for attempt in range(tries):
            ep = ENDPOINTS[self.ep % len(ENDPOINTS)]
            gap = 0.25 - (time.time() - self.last)
            if gap > 0:
                time.sleep(gap)
            self.last = time.time()
            p = subprocess.run(["curl", "-sS", "-m", "45", "-H", "content-type: application/json", "-d", body, ep],
                               capture_output=True, text=True)
            host = ep.split("//")[1]
            try:
                j = json.loads(p.stdout)
            except Exception:
                self.ledger[f"{host}|{method}|timeout_or_http"] += 1
                err = "timeout" if p.returncode == 28 else "http"
                self.ep += 1
                time.sleep(min(2 ** attempt, 20))
                continue
            if "result" in j and j["result"] is not None:
                self.ledger[f"{host}|{method}|ok"] += 1
                return j["result"], None
            msg = json.dumps(j.get("error", j))[:200].lower()
            self.ledger[f"{host}|{method}|rpc_error"] += 1
            if any(s in msg for s in ("range", "too many", "exceed", "limit exceeded", "10000", "more than")):
                if "request limit" not in msg:
                    return None, "range"
            err = "rpc"
            self.ep += 1          # archive/limit/other: try the other endpoint
            time.sleep(min(2 ** attempt, 20))
        return None, err


def hx(v):
    return int(v, 16)


def block_ts(rpc, n):
    r, e = rpc.call("eth_getBlockByNumber", [hex(n), False])
    if r is None:
        raise RuntimeError(f"block {n}: {e}")
    return hx(r["timestamp"])


def block_at_or_before(rpc, ts, head, head_ts, cache):
    if ts in cache:
        return cache[ts]
    if ts >= head_ts:
        return head
    n = max(1, head - (head_ts - ts) // 2)
    for _ in range(8):
        d = ts - block_ts(rpc, n)
        if 0 <= d < 2:
            break
        n += d // 2 if d > 0 else -((-d + 1) // 2)
    while block_ts(rpc, n) > ts:
        n -= 1
    while block_ts(rpc, n + 1) <= ts:
        n += 1
    cache[ts] = n
    return n


# ---------------------------------------------------------------- statistics
def log_binom_pmf(i, n, p):
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def binom_cdf(x, n, p):
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0 if x < n else 1.0
    return min(1.0, sum(math.exp(log_binom_pmf(i, n, p)) for i in range(0, x + 1)))


def cp_upper(x, n, alpha=ALPHA):
    if x >= n:
        return 1.0
    if x == 0:
        return 1 - alpha ** (1.0 / n)
    lo, hi = x / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_lower(x, n, alpha=ALPHA):
    if x == 0:
        return 0.0
    lo, hi = 0.0, x / n
    for _ in range(100):
        mid = (lo + hi) / 2
        if 1 - binom_cdf(x - 1, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- fetch
def feed_contract(rpc, f, state):
    """Resolve the contract and topic filter for a feed; remember what was resolved."""
    if f["kind"] == "chainlink":
        agg, e = rpc.call("eth_call", [{"to": f["proxy"], "data": SEL["aggregator()"]}, "latest"])
        ph, e2 = rpc.call("eth_call", [{"to": f["proxy"], "data": SEL["phaseId()"]}, "latest"])
        if agg is None or ph is None:
            raise RuntimeError(f"{f['id']}: cannot resolve aggregator ({e},{e2})")
        addr = "0x" + agg[-40:]
        return dict(address=addr, topics=[T_CL_ANSWER], resolved=dict(aggregator=addr, phaseId=hx(ph)))
    name = f["dapi"].encode().ljust(32, b"\0").hex()
    sel = selector("dapiNameToDataFeedId(bytes32)")
    fid, e = rpc.call("eth_call", [{"to": A3_SERVER, "data": sel + name}, "latest"])
    if fid is None or hx(fid) == 0:
        raise RuntimeError(f"{f['id']}: dAPI name not set ({e})")
    return dict(address=A3_SERVER, topics=[T_A3_SET, fid], resolved=dict(dataFeedId=fid))


def parse_log(f, lg):
    b, i = hx(lg["blockNumber"]), hx(lg["logIndex"])
    if f["kind"] == "chainlink":
        price = int(lg["topics"][1], 16)
        if price >= 1 << 255:
            price -= 1 << 256
        return dict(b=b, i=i, t=hx(lg["data"]), p=price, r=hx(lg["topics"][2]))
    data = lg["data"][2:]
    price = int(data[:64], 16)
    if price >= 1 << 223:
        price -= 1 << 224
    return dict(b=b, i=i, t=int(data[64:128], 16), p=price)


def load_events(raw, f):
    path = os.path.join(raw, f["id"] + ".jsonl")
    ev = {}
    if os.path.exists(path):
        for ln in open(path):
            d = json.loads(ln)
            ev[(d["b"], d["i"])] = d
    return sorted(ev.values(), key=lambda d: (d["t"], d["b"], d["i"])), path


def meta_path(raw, f):
    return os.path.join(raw, f["id"] + ".meta.json")


def do_fetch(raw, rpc, win_start, win_end_ts, lookback_extra=0):
    os.makedirs(raw, exist_ok=True)
    head_hex, e = rpc.call("eth_blockNumber", [])
    if head_hex is None:
        raise RuntimeError("cannot read head: " + str(e))
    head = hx(head_hex) - SAFE_BLOCKS
    head_ts = block_ts(rpc, head)
    cache = {}
    report = []
    for f in FEEDS:
        mp = meta_path(raw, f)
        meta = json.load(open(mp)) if os.path.exists(mp) else {}
        info = feed_contract(rpc, f, meta)
        if meta.get("resolved") and meta["resolved"] != info["resolved"]:
            report.append(f"{f['id']}: RESOLVED CONTRACT CHANGED {meta['resolved']} -> {info['resolved']}; stop and read WF1_registration.md 6.4")
            continue
        lookback_ts = win_start - f["G"] - PAD
        first_block = block_at_or_before(rpc, lookback_ts, head, head_ts, cache)
        cursor = meta.get("fetched_to", first_block - 1)
        end_block = head if win_end_ts is None else min(head, block_at_or_before(rpc, win_end_ts + f["G"] + PAD, head, head_ts, cache))
        path = os.path.join(raw, f["id"] + ".jsonl")
        n_new, span = 0, SPAN
        a = cursor + 1
        failed = None
        while a <= end_block:
            b = min(a + span - 1, end_block)
            r, err = rpc.call("eth_getLogs", [{"address": info["address"], "topics": info["topics"],
                                               "fromBlock": hex(a), "toBlock": hex(b)}])
            if r is None:
                if err == "range" and span > 500:
                    span //= 2
                    continue
                failed = f"getLogs {a}-{b}: {err}"
                break
            with open(path, "a") as fh:
                for lg in r:
                    fh.write(json.dumps(parse_log(f, lg)) + "\n")
            n_new += len(r)
            cursor = b
            meta.update(fetched_to=cursor, resolved=info["resolved"])
            json.dump(meta, open(mp, "w"))
            a = b + 1
        ts_cursor = block_ts(rpc, cursor) if cursor >= first_block else None
        meta["fetched_to_ts"] = ts_cursor
        json.dump(meta, open(mp, "w"))
        report.append(f"{f['id']}: +{n_new} events, fetched to block {cursor} (ts {ts_cursor})" + (f"  FETCH FAILED: {failed}" if failed else ""))
    rpc.save()
    return report


# ---------------------------------------------------------------- analysis
def analyze_feed(raw, f, win_start, n_bound):
    ev, _ = load_events(raw, f)
    mp = meta_path(raw, f)
    meta = json.load(open(mp)) if os.path.exists(mp) else {}
    head_ts = meta.get("fetched_to_ts")
    G = f["G"]
    ts = [e["t"] for e in ev]
    # integrity: Chainlink round ids must be consecutive; a hole is a retrieval problem, not a feed gap
    suspect = []
    if f["kind"] == "chainlink":
        byr = sorted(ev, key=lambda e: e["r"])
        for a, b in zip(byr, byr[1:]):
            if b["r"] != a["r"] + 1:
                suspect.append((min(a["t"], b["t"]), max(a["t"], b["t"]), a["r"], b["r"]))
    res = dict(feed=f["id"], provider=f["provider"], G=G, n_events=len(ev), head_ts=head_ts, suspect_holes=len(suspect))
    fails, unresolved, pending, resolved = [], 0, 0, 0
    gaps_at, moved = [], 0
    ages = []
    for j in range(n_bound):
        t = win_start + STEP * j
        k = bisect.bisect_left(ts, t)          # ts[k] is the first update with ts >= t (next); ts[k-1] < t is prev
        prev = ts[k - 1] if k > 0 else None
        nxt = ts[k] if k < len(ts) else None
        if head_ts is None or (nxt is None and head_ts < t):
            pending += 1
            continue
        if any(a < t <= b for a, b, _, _ in suspect):
            unresolved += 1
            continue
        if prev is None:
            prev_eff = win_start - G - PAD       # nothing in the look-back: gap is longer than G + PAD
            fail = True if nxt is not None or head_ts - prev_eff > G else False
            g = (nxt - prev_eff) if nxt is not None else None
        elif nxt is not None:
            g = nxt - prev
            fail = g > G
        elif head_ts - prev > G:
            g, fail = None, True
        else:
            pending += 1
            continue
        resolved += 1
        ages.append(t - prev if prev is not None else G + PAD)
        if fail:
            fails.append(j)
        if g is not None:
            gaps_at.append(g)
        if prev is not None and nxt is not None:
            p0, p1 = ev[k - 1]["p"], ev[k]["p"]
            if p0 and abs(p1 - p0) > TOL * abs(p0):
                moved += 1
    n, x = resolved, len(fails)
    runs = []
    for j in fails:
        if runs and j == runs[-1][1] + 1:
            runs[-1][1] = j
        else:
            runs.append([j, j])
    # all-seconds failure fraction over the resolved part of the window, from the update list
    t_end = min(win_start + STEP * n_bound, head_ts or win_start)
    over = 0
    for a, b in zip(ts, ts[1:]):
        lo, hi = max(a, win_start), min(b, t_end)
        if hi > lo and b - a > G:
            over += hi - lo
    span_s = max(1, t_end - win_start)
    gs = sorted(gaps_at)
    qs = lambda q: gs[min(len(gs) - 1, int(q * len(gs)))] if gs else None
    ag = sorted(ages)
    res.update(n=n, x=x, pending=pending, unresolved=unresolved,
               phat=(x / n if n else None),
               upper_exact=cp_upper(x, n) if n else None,
               upper_3n=(3.0 / n if n and x == 0 else None),
               lower_cp=cp_lower(x, n) if n else None,
               runs=len(runs), max_run=max([b - a + 1 for a, b in runs], default=0),
               run_list=[(win_start + STEP * a, win_start + STEP * b) for a, b in runs][:50],
               gap_median=qs(0.5), gap_p99=qs(0.99), gap_max=(gs[-1] if gs else None),
               age_median=(ag[len(ag) // 2] if ag else None), age_max=(ag[-1] if ag else None),
               tol_moved_share=(moved / n if n else None),
               allsec_over_fraction=over / span_s)
    return res


def verdict_feed(r):
    n, x = r["n"], r["x"]
    if n == 0:
        return "no resolved boundary"
    if n < 1497:
        return "J0: n < 1,497, so the exact bound cannot reach 0.002 even with no failure; no verdict"
    U = r["upper_exact"]
    if r["unresolved"] or r["pending"]:
        tag = f" (unresolved {r['unresolved']}, pending {r['pending']}: not final)"
    else:
        tag = ""
    if r["lower_cp"] > BAND_LO:
        s = "J-: the lower 95% bound exceeds 0.002; the band lower end is contradicted for this feed"
    elif U <= BAND_LO:
        s = "J1: upper bound at or below 0.002; this feed supports the band lower end"
    elif U <= BAND_HI:
        s = "J2: upper bound between 0.002 and 0.01; this feed lies inside the band and does not support its lower end"
    else:
        s = "J3: upper bound above 0.01; this feed is not covered by the band"
    return s + tag


def do_analyze(raw, win_start, n_bound, out=sys.stdout):
    results = [analyze_feed(raw, f, win_start, n_bound) for f in FEEDS]
    P = lambda *a: print(*a, file=out)
    P(f"window start {iso(win_start)}, boundaries {n_bound}, step {STEP} s")
    for r in results:
        P("")
        P(f"[{r['feed']}] provider {r['provider']}, G = {r['G']} s, events {r['n_events']}, "
          f"head ts {iso(r['head_ts']) if r['head_ts'] else None}")
        P(f"  resolved n = {r['n']}, failures x = {r['x']}, pending {r['pending']}, unresolved {r['unresolved']}, "
          f"integrity holes {r['suspect_holes']}")
        if r["n"]:
            P(f"  p_hat = {r['phat']:.6f}, exact upper = {r['upper_exact']:.6f}"
              + (f", 3/n = {r['upper_3n']:.6f}" if r["upper_3n"] is not None else "")
              + f", CP lower = {r['lower_cp']:.6f}")
            P(f"  failure runs = {r['runs']}, longest run = {r['max_run']} boundaries; "
              f"gap median/p99/max = {r['gap_median']}/{r['gap_p99']}/{r['gap_max']} s; "
              f"age at boundary median/max = {r['age_median']}/{r['age_max']} s")
            P(f"  descriptive: share of boundaries whose gap price change exceeds 0.25% = {r['tol_moved_share']:.4f}; "
              f"all-seconds fraction in gaps over G = {r['allsec_over_fraction']:.6f}")
            for a, b in r["run_list"][:10]:
                P(f"  run: {iso(a)} .. {iso(b)}")
            P("  verdict: " + verdict_feed(r))
    prov = {}
    for r in results:
        if r["n"]:
            prov.setdefault(r["provider"], []).append(verdict_feed(r).startswith("J1"))
    P("")
    P("overall: providers with every included feed at J1: "
      + (", ".join(p for p, v in prov.items() if all(v)) or "none")
      + "; providers with any feed not J1: " + (", ".join(p for p, v in prov.items() if not all(v)) or "none"))
    return results


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- verify (independent state read)
def do_verify(raw, rpc, win_start, n_bound):
    head_hex, _ = rpc.call("eth_blockNumber", [])
    head = hx(head_hex) - SAFE_BLOCKS
    head_ts = block_ts(rpc, head)
    cache = {}
    rnd = random.Random(VERIFY_SEED + head)
    out = []
    for f in FEEDS:
        ev, _ = load_events(raw, f)
        meta = json.load(open(meta_path(raw, f)))
        done_ts = meta.get("fetched_to_ts") or 0
        js = [j for j in range(n_bound) if win_start + STEP * j <= done_ts and win_start + STEP * j >= head_ts - VERIFY_DEPTH]
        sample = rnd.sample(js, min(VERIFY_SAMPLE, len(js)))
        info = feed_contract(rpc, f, {})
        by_block = sorted(ev, key=lambda e: (e["b"], e["i"]))
        blocks = [e["b"] for e in by_block]
        ok = bad = err = 0
        for j in sample:
            t = win_start + STEP * j
            bn = block_at_or_before(rpc, t, head, head_ts, cache)
            if f["kind"] == "chainlink":
                r, e = rpc.call("eth_call", [{"to": f["proxy"], "data": SEL["latestRoundData()"]}, hex(bn)])
                if r is None:
                    err += 1; continue
                updated = hx("0x" + r[2 + 64 * 3:2 + 64 * 4])
            else:
                r, e = rpc.call("eth_call", [{"to": A3_SERVER, "data": selector("dataFeeds(bytes32)") + info["topics"][1][2:]}, hex(bn)])
                if r is None:
                    err += 1; continue
                updated = hx("0x" + r[2 + 64:2 + 128])
            k = bisect.bisect_right(blocks, bn)
            logged = by_block[k - 1]["t"] if k else None
            if logged == updated:
                ok += 1
            else:
                bad += 1
                out.append(f"  mismatch {f['id']} t={iso(t)} block {bn}: state {updated} vs log {logged}")
        line = f"{f['id']}: sampled {len(sample)}, equal {ok}, different {bad}, state-read failed {err}"
        out.insert(0, line)
        with open(os.path.join(raw, "verify_log.jsonl"), "a") as fh:
            fh.write(json.dumps(dict(feed=f["id"], head=head, sampled=len(sample), equal=ok, different=bad, failed=err)) + "\n")
    rpc.save()
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "fetch", "analyze", "verify", "pilot"])
    ap.add_argument("--raw", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "raw", "WF1"))
    ap.add_argument("--start", default="2026-10-27T00:00:00Z", help="pilot start (ISO, UTC)")
    ap.add_argument("--n", type=int, default=20, help="pilot boundaries")
    a = ap.parse_args()

    if a.cmd == "plan":
        end = WINDOW_START + STEP * N_BOUNDARIES
        print(f"window {iso(WINDOW_START)} .. {iso(end)} (exclusive), {N_BOUNDARIES} boundaries per feed, {len(FEEDS)} feeds")
        blocks = (end - WINDOW_START) // 2
        for f in FEEDS:
            print(f"  {f['id']}: G={f['G']} s; about {blocks // SPAN + 2} getLogs calls over the whole window; {f['declared']}")
        n_alpha = lambda n: 1 - ALPHA ** (1 / n)
        print(f"exact upper bound for x=0 at n={N_BOUNDARIES}: {n_alpha(N_BOUNDARIES):.6f}; 3/n = {3 / N_BOUNDARIES:.6f}")
        print(f"sanity: x=0, n=1728 gives {n_alpha(1728):.5f} (existing Pyth measurement 0.00173)")
        print(f"sanity: CP upper x=3, n={N_BOUNDARIES} = {cp_upper(3, N_BOUNDARIES):.6f}")
        return

    ledger = os.path.join(a.raw, "ledger.json")
    os.makedirs(a.raw, exist_ok=True)
    rpc = Rpc(ledger)

    if a.cmd == "fetch":
        end_ts = WINDOW_START + STEP * N_BOUNDARIES
        for ln in do_fetch(a.raw, rpc, WINDOW_START, end_ts):
            print(ln)
    elif a.cmd == "analyze":
        do_analyze(a.raw, WINDOW_START, N_BOUNDARIES)
    elif a.cmd == "verify":
        for ln in do_verify(a.raw, rpc, WINDOW_START, N_BOUNDARIES):
            print(ln)
    elif a.cmd == "pilot":
        start = int(dt.datetime.strptime(a.start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())
        if start < WINDOW_START + STEP * N_BOUNDARIES and start + STEP * a.n > WINDOW_START:
            sys.exit("pilot must not overlap the registered window")
        raw = a.raw + "_pilot"
        os.makedirs(raw, exist_ok=True)
        rpc.ledger_path = os.path.join(raw, "ledger.json")
        print(f"PILOT (functional test, not a result): start {iso(start)}, {a.n} boundaries")
        for ln in do_fetch(raw, rpc, start, start + STEP * a.n):
            print(ln)
        do_analyze(raw, start, a.n)
        print("")
        print("verify (state read against logs, pilot boundaries):")
        for ln in do_verify(raw, rpc, start, a.n):
            print(ln)
        print("ledger:", json.dumps(json.load(open(rpc.ledger_path)), sort_keys=True))


if __name__ == "__main__":
    main()
