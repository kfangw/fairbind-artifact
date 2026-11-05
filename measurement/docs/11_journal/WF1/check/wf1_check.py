#!/usr/bin/env python3 -I
"""WF1 independent check code.

WF1_registration.md one document only reading written recomputation code. measured script(wf1_measure.py) not open did not.
standard library only uses.

sub command
  check     raw event jsonl takes per boundary verdicts and feed, provider statements outputs.
  fetch     (optional) public RPC events direct takes same form jsonl uses.
            request interval registration window and if overlapping --unlock-window without not run not.
  selftest  synthetic data verdict registration as written come out tests. network not used not.

input jsonl one line event is one.
  {"feed": "CL-BTCUSD", "time": 1788912000, "roundId": 123, "value": 6500000000000}
time instead updatedAt, timestamp, ts also accepts. roundId Chainlink only exists(if absent continuity check skips).
numbers integer, decimal string, 0x prefix 16 string accepts.
"""
import argparse
import bisect
import calendar
import json
import math
import sys
import time as _time
import urllib.request

# ----------------------------------------------------------------------------
# registration constant (WF1_registration.md 2.2, 4, 5 (sec.))
# ----------------------------------------------------------------------------
WSTART = calendar.timegm((2026, 9, 9, 0, 0, 0))
WEND = calendar.timegm((2026, 10, 27, 0, 0, 0))
STEP = 300
FEEDS = {  # feed: declared limit grace plus G (seconds)
    "CL-BTCUSD": 1260,
    "CL-ETHUSD": 1260,
    "A3-BTCUSD": 90000,
    "A3-ETHUSD": 90000,
}
PROVIDER_NAME = {"CL": "Chainlink", "A3": "API3"}
T_LOW = 0.002   # band below end
T_HIGH = 0.01   # band upper end
ALPHA = 0.05
TOL_PRICE = 0.0025


def exact_upper0(n):
    """x = 0 days when exact upper 1 - 0.05^(1/n)."""
    return -math.expm1(math.log(ALPHA) / n)


MIN_N = math.ceil(math.log(ALPHA) / math.log(1.0 - T_LOW))  # definite boundary lower, registration 1,497


# ----------------------------------------------------------------------------
# Clopper-Pearson one-sided 95%
# ----------------------------------------------------------------------------
def _logpmf(k, n, p):
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def _cdf_le(x, n, p):
    """P(X <= x)."""
    return min(1.0, sum(math.exp(_logpmf(k, n, p)) for k in range(0, x + 1)))


def _sf_ge(x, n, p):
    """P(X >= x)."""
    if x <= 0:
        return 1.0
    if x <= n // 2:
        return max(0.0, 1.0 - _cdf_le(x - 1, n, p))
    return min(1.0, sum(math.exp(_logpmf(k, n, p)) for k in range(x, n + 1)))


def cp_upper(x, n):
    """95% one-sided upper: P(X <= x | p) = 0.05 h."""
    if x >= n:
        return 1.0
    if x == 0:
        return exact_upper0(n)
    lo, hi = x / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _cdf_le(x, n, mid) > ALPHA:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_lower(x, n):
    """95% one-sided lower: P(X >= x | p) = 0.05 h."""
    if x <= 0:
        return 0.0
    lo, hi = 0.0, x / n
    for _ in range(100):
        mid = (lo + hi) / 2
        if _sf_ge(x, n, mid) < ALPHA:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def classify(n, x):
    """(symbol list, U, L). symbols J1, J2, J3, J-, J0."""
    if n < MIN_N:
        return ["J0"], None, None
    U = cp_upper(x, n)
    L = cp_lower(x, n)
    syms = ["J1" if U <= T_LOW else ("J2" if U <= T_HIGH else "J3")]
    if L > T_LOW:
        syms.append("J-")
    return syms, U, L


# ----------------------------------------------------------------------------
# input read
# ----------------------------------------------------------------------------
def to_int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("boolean value")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s)


def load_events(path):
    """feed per event list {feed: [(time, round|None, value|None), ...]}."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            feed = r["feed"]
            t = None
            for k in ("time", "updatedAt", "timestamp", "ts"):
                if k in r and r[k] is not None:
                    t = to_int(r[k])
                    break
            if t is None:
                raise ValueError("%s:%d time field none" % (path, ln))
            rid = None
            for k in ("roundId", "round_id", "round"):
                if k in r and r[k] is not None:
                    rid = to_int(r[k])
                    break
            val = None
            for k in ("value", "current", "answer"):
                if k in r and r[k] is not None:
                    val = to_int(r[k])
                    break
            out.setdefault(feed, []).append((t, rid, val))
    return out


# ----------------------------------------------------------------------------
# per boundary verdict (event column linearly scans)
# ----------------------------------------------------------------------------
OK, FAIL, PENDING = "ok", "fail", "pending"


def analyze_feed(events, G, start=WSTART, end=WEND, unread=None):
    """registration 2.2 (sec.), 6.3 (sec.) following per boundary success, failure, undetermined determines.

    events: [(time, round|None, value|None)], order and duplicates do not matter.
    unread: [(a, b), ...] not read not time interval(query failure). this interval boundary gap and if overlapping undetermined.
    """
    N = (end - start) // STEP
    # same (time, round) complete duplicates into one merges.
    seen = {}
    for (t, rid, v) in events:
        seen[(t, rid)] = (t, rid, v)
    evs = sorted(seen.values(), key=lambda e: (e[0], -1 if e[1] is None else e[1]))

    # time column u (strictly increasing). same times if two last value only uses.
    U, V = [], []
    for (t, rid, v) in evs:
        if U and U[-1] == t:
            V[-1] = v
        else:
            U.append(t)
            V.append(v)

    # round id continuity check: joined two events round id difference 1 otherwise after event time as suspect mark.
    suspect_next = set()
    for a, b in zip(evs, evs[1:]):
        if a[1] is not None and b[1] is not None and b[1] - a[1] != 1:
            suspect_next.add(b[0])

    unread = unread or []
    status = [None] * N
    gaps_at = [None] * N      # boundary containing gap length (definite when)
    age_at = [None] * N       # boundary moment last update age
    pair_at = [None] * N      # (previous value, next value)
    i = 0
    for j in range(N):
        t = start + STEP * j
        while i < len(U) and U[i] < t:   # U[i] t at least first update
            i += 1
        prev = U[i - 1] if i > 0 else None
        nxt = U[i] if i < len(U) else None
        # suspect and query failure interval
        if nxt is not None and nxt in suspect_next:
            # suspect gap (immediately prior event time, nxt] boundary containing gap and equal.
            status[j] = PENDING
            continue
        lo = prev if prev is not None else -math.inf
        hi = nxt if nxt is not None else math.inf
        if any(a < hi and b > lo for (a, b) in unread):
            status[j] = PENDING
            continue
        if nxt is not None:
            if prev is None:
                status[j] = FAIL      # prior in range update none
            else:
                g = nxt - prev
                status[j] = FAIL if g > G else OK
                gaps_at[j] = g
                age_at[j] = t - prev
                pair_at[j] = (V[i - 1], V[i])
        else:
            if prev is None:
                status[j] = FAIL      # empty feed
            elif t - prev > G:
                status[j] = FAIL
                age_at[j] = t - prev
            else:
                status[j] = PENDING
    return {"N": N, "status": status, "gaps": gaps_at, "ages": age_at, "pairs": pair_at,
            "U": U, "suspect_next": suspect_next}


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[k]


def summarize_feed(name, events, G, start=WSTART, end=WEND, unread=None):
    r = analyze_feed(events, G, start, end, unread)
    st = r["status"]
    N = r["N"]
    x = st.count(FAIL)
    p = st.count(PENDING)
    n = N - p
    syms, U, L = classify(n, x)
    res = {"feed": name, "G": G, "N": N, "n": n, "x": x, "pending": p}
    res["point"] = x / n if n else None
    res["U"] = U
    res["L"] = L
    res["U_3_over_n"] = 3.0 / n if (x == 0 and n) else None
    res["symbols"] = syms
    # undetermined present when: all failure and all success assumed verdict (6.3 (sec.))
    if p:
        worst = classify(N, x + p)[0]
        best = classify(N, x)[0]
        res["worst_symbols"], res["best_symbols"] = worst, best
        res["worst_U"] = cp_upper(x + p, N) if N >= MIN_N else None
        res["best_U"] = cp_upper(x, N) if N >= MIN_N else None
        if "J0" in syms:
            res["verdict"] = "J0"
        elif worst == best:
            res["verdict"] = "+".join(best)
        else:
            res["verdict"] = "pending"
    else:
        res["verdict"] = "+".join(syms)
    # failure time, consecutive interval
    fail_times = [start + STEP * j for j, s in enumerate(st) if s == FAIL]
    runs, longest, cur = 0, 0, 0
    for s in st:
        if s == FAIL:
            cur += 1
            if cur == 1:
                runs += 1
            longest = max(longest, cur)
        else:
            cur = 0
    res["fail_runs"] = runs
    res["fail_longest_run"] = longest
    res["fail_times"] = fail_times
    res["pending_times"] = [start + STEP * j for j, s in enumerate(st) if s == PENDING]
    if x and longest > 1:
        res["note_unit"] = "boundary unit, consecutive failure included"
    # describe indicator
    U_ = r["U"]
    gaps = sorted(b - a for a, b in zip(U_, U_[1:]) if start <= b < end + 10 ** 9 and a < end)
    res["gap_median"] = _quantile(gaps, 0.5)
    res["gap_p99"] = _quantile(gaps, 0.99)
    res["gap_max"] = gaps[-1] if gaps else None
    ages = sorted(a for a in r["ages"] if a is not None)
    res["age_median"] = _quantile(ages, 0.5)
    res["age_max"] = ages[-1] if ages else None
    pairs = [pr for pr in r["pairs"] if pr is not None and pr[0] is not None and pr[1] is not None]
    if pairs:
        big = sum(1 for (a, b) in pairs if abs(b - a) > TOL_PRICE * abs(a))
        res["price_change_gt_0_25pct"] = big / len(pairs)
    else:
        res["price_change_gt_0_25pct"] = None
    # all seconds among G over gaps occupying ratio (gap whole length counts)
    if not U_:
        res["fail_time_fraction"] = 1.0
    else:
        tot = 0
        for a, b in zip(U_, U_[1:]):
            if b - a > G:
                tot += max(0, min(b, end) - max(a, start))
        res["fail_time_fraction"] = tot / (end - start)
    return res


# ----------------------------------------------------------------------------
# provider, whole statement (5.3 (sec.))
# ----------------------------------------------------------------------------
SENT = {
    "P1": "provider {p} two feed band below end supports.",
    "P2": "provider two(Chainlink, API3) feed in four w_avail 95% upper bound 0.002 is at most. band below end this measurement supports. this values Base upper two provider, two assets, 48 days, declared limit G_f is limited.",
    "P3": "this measurement supporting what {p}only. not support not provider name and results recorded. manuscript general statements not used not.",
    "P4": "this measurement band below end not support cannot. below end basis existing 6 days Pyth measured(0.00173) and input waiting seller structural 0only.",
    "C1": "Base upper Chainlink Data Feeds BTC/USD and ETH/USD w_avail 95% upper bound 0.002 is at most. band below end this provider one at one place is supported. other to provider not state not. values two assets, 48 days, declared limit 1,260 s is limited.",
    "C2": "its in feeds only is supported. not support not feed name and results recorded. manuscript general statements not used not.",
    "C3": "this measurement band below end not support cannot. below end basis existing 6 days Pyth measured(0.00173) and input waiting seller structural 0only.",
}


def provider_of(feed):
    return feed.split("-")[0]


def overall(results, api3_confirmed):
    """results: {feed: summary}. provider and whole statements determines."""
    by_prov = {}
    for f, r in results.items():
        by_prov.setdefault(provider_of(f), []).append(r)

    def is_p1(rs):
        return bool(rs) and all(r["verdict"] == "J1" for r in rs)

    out = {"providers": {}}
    if api3_confirmed:
        provs = [p for p in ("CL", "A3") if p in by_prov]
        for p in provs:
            out["providers"][PROVIDER_NAME.get(p, p)] = "P1" if is_p1(by_prov[p]) else "ratioP1"
        good = [p for p in provs if is_p1(by_prov[p])]
        if len(good) == 2:
            out["sentence_id"] = "P2"
            out["sentence"] = SENT["P2"]
        elif len(good) == 1:
            out["sentence_id"] = "P3"
            out["sentence"] = SENT["P3"].format(p=PROVIDER_NAME.get(good[0], good[0]))
        else:
            out["sentence_id"] = "P4"
            out["sentence"] = SENT["P4"]
    else:
        cl = by_prov.get("CL", [])
        flags = [r["verdict"] == "J1" for r in cl]
        out["providers"]["Chainlink"] = "P1" if is_p1(cl) else "ratioP1"
        out["providers"]["API3"] = "describe statistics only(declared limit unconfirmed), verdict statement none"
        if cl and all(flags):
            out["sentence_id"] = "C1"
            out["sentence"] = SENT["C1"]
        elif any(flags):
            out["sentence_id"] = "C2"
            out["sentence"] = SENT["C2"]
            out["j1_feeds"] = [r["feed"] for r in cl if r["verdict"] == "J1"]
            out["not_j1_feeds"] = [(r["feed"], r["verdict"]) for r in cl if r["verdict"] != "J1"]
        else:
            out["sentence_id"] = "C3"
            out["sentence"] = SENT["C3"]
    return out


# ----------------------------------------------------------------------------
# keccak256 (RPC optional in path event signature and function selector makes)
# ----------------------------------------------------------------------------
def _keccak_consts():
    rc, R = [], 1
    for _ in range(24):
        c = 0
        for j in range(7):
            R = ((R << 1) ^ ((R >> 7) * 0x71)) % 256
            if R & 2:
                c ^= 1 << ((1 << j) - 1)
        rc.append(c)
    rot = [[0] * 5 for _ in range(5)]
    x, y = 1, 0
    for t in range(24):
        rot[x][y] = ((t + 1) * (t + 2) // 2) % 64
        x, y = y, (2 * x + 3 * y) % 5
    return rc, rot


_RC, _ROT = _keccak_consts()
_M64 = (1 << 64) - 1


def _rol(v, n):
    n %= 64
    return ((v << n) | (v >> (64 - n))) & _M64 if n else v


def keccak256(data):
    rate = 136
    msg = bytearray(data)
    msg.append(0x01)
    while len(msg) % rate:
        msg.append(0)
    msg[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            A[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        for rnd in range(24):
            C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
            D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    A[x][y] ^= D[x]
            B = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _ROT[x][y])
            for x in range(5):
                for y in range(5):
                    A[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y] & _M64) & B[(x + 2) % 5][y])
            A[0][0] ^= _RC[rnd]
    out = b""
    for i in range(4):
        out += A[i % 5][i // 5].to_bytes(8, "little")
    return out


# ----------------------------------------------------------------------------
# optional: public RPC raw data direct fetch
# ----------------------------------------------------------------------------
RPCS = ["https://base-rpc.publicnode.com", "https://mainnet.base.org"]
CHAINLINK_AGG = {
    "CL-BTCUSD": "0xe5ec87a39445b8d5b751b116802a53c5ae7e9df1",
    "CL-ETHUSD": "0x05c84a58FE042275b37db038bAAcD15F410c7bB0",
}
API3_SERVER = "0x709944a48cAf83535e43471680fDA4905FB3920a"
API3_DAPI = {"A3-BTCUSD": "BTC/USD", "A3-ETHUSD": "ETH/USD"}
_LEDGER = {}


def rpc(method, params, retries=6):
    waits = [1, 2, 4, 8, 16, 20]
    last = None
    for attempt in range(retries):
        url = RPCS[attempt % len(RPCS)]
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "User-Agent": "wf1-check"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                j = json.loads(resp.read().decode())
            if "error" in j:
                last = j["error"]
                _LEDGER[(url, method, "rpc_error")] = _LEDGER.get((url, method, "rpc_error"), 0) + 1
            else:
                _LEDGER[(url, method, "ok")] = _LEDGER.get((url, method, "ok"), 0) + 1
                return j["result"]
        except Exception as e:  # network errors also query as failure counts
            last = repr(e)
            _LEDGER[(url, method, "timeout_or_http")] = _LEDGER.get((url, method, "timeout_or_http"), 0) + 1
        _time.sleep(waits[min(attempt, len(waits) - 1)])
    raise RuntimeError("RPC failure: %s %s" % (method, last))


def block_ts(n):
    b = rpc("eth_getBlockByNumber", [hex(n), False])
    return int(b["timestamp"], 16)


def first_block_at_or_after(ts, hi):
    lo = 1
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) >= ts:
            hi = mid
        else:
            lo = mid + 1
    return lo


def fetch_events(feeds, t_from, t_to, out_path):
    """[t_from, t_to) time interval events accepts. read interval end block event time(updatedAt, timestamp) and is separate."""
    latest = int(rpc("eth_blockNumber", []), 16)
    b0 = first_block_at_or_after(t_from, latest)
    b1 = first_block_at_or_after(t_to, latest) - 1
    topic_cl = "0x" + keccak256(b"AnswerUpdated(int256,uint256,uint256)").hex()
    topic_a3 = "0x" + keccak256(b"UpdatedBeaconSetWithBeacons(bytes32,int224,uint32)").hex()
    sel = "0x" + keccak256(b"dapiNameToDataFeedId(bytes32)")[:4].hex()
    rows = []
    for feed in feeds:
        if feed in CHAINLINK_AGG:
            addr, topics = CHAINLINK_AGG[feed], [topic_cl]
        else:
            name = API3_DAPI[feed].encode().ljust(32, b"\0").hex()
            fid = rpc("eth_call", [{"to": API3_SERVER, "data": sel + name}, "latest"])
            addr, topics = API3_SERVER, [topic_a3, fid]
        lo = b0
        span = 50000
        while lo <= b1:
            hi = min(b1, lo + span - 1)
            try:
                logs = rpc("eth_getLogs", [{"address": addr, "topics": topics,
                                            "fromBlock": hex(lo), "toBlock": hex(hi)}])
            except RuntimeError:
                if span > 1000:
                    span //= 2
                    continue
                raise
            for lg in logs:
                tp = lg["topics"]
                data = lg["data"][2:]
                if feed in CHAINLINK_AGG:
                    cur = int(tp[1], 16)
                    if cur >= 1 << 255:
                        cur -= 1 << 256
                    rows.append({"feed": feed, "time": int(data[:64], 16), "roundId": int(tp[2], 16),
                                 "value": cur, "block": int(lg["blockNumber"], 16),
                                 "logIndex": int(lg["logIndex"], 16)})
                else:
                    v = int(data[:64], 16)
                    if v >= 1 << 255:
                        v -= 1 << 256
                    rows.append({"feed": feed, "time": int(data[64:128], 16), "value": v,
                                 "block": int(lg["blockNumber"], 16), "logIndex": int(lg["logIndex"], 16)})
            lo = hi + 1
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows, (b0, b1)


# ----------------------------------------------------------------------------
# output
# ----------------------------------------------------------------------------
def fmt(v, nd=6):
    return "-" if v is None else ("%.*f" % (nd, v) if isinstance(v, float) else str(v))


def render(results, ov, start, end):
    lines = []
    lines.append("window %s or more %s below, boundary spacing %d s" % (
        _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(start)),
        _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(end)), STEP))
    lines.append("per feed results (U 95% one-sided upper, L lower)")
    for f, r in results.items():
        lines.append("  %s G=%d N=%d n=%d x=%d undetermined=%d point estimate=%s U=%s L=%s verdict=%s" % (
            f, r["G"], r["N"], r["n"], r["x"], r["pending"], fmt(r["point"]), fmt(r["U"]),
            fmt(r["L"]), r["verdict"]))
        if r["x"] == 0 and r["U_3_over_n"] is not None:
            lines.append("    3/n approximate %s" % fmt(r["U_3_over_n"]))
        if r["pending"]:
            lines.append("    worst U=%s best U=%s worst verdict=%s best verdict=%s" % (
                fmt(r.get("worst_U")), fmt(r.get("best_U")),
                "+".join(r["worst_symbols"]), "+".join(r["best_symbols"])))
        lines.append("    failure consecutive interval %d, most long consecutive %d%s" % (
            r["fail_runs"], r["fail_longest_run"], (", " + r["note_unit"]) if "note_unit" in r else ""))
        lines.append("    gap median %s, 99th percentile %s, maximum %s, boundary age median %s, maximum %s, 0.25%% over change ratio %s, failure time ratio %s" % (
            r["gap_median"], r["gap_p99"], r["gap_max"], r["age_median"], r["age_max"],
            fmt(r["price_change_gt_0_25pct"], 4), fmt(r["fail_time_fraction"], 6)))
    lines.append("provider verdict: %s" % json.dumps(ov["providers"], ensure_ascii=False))
    lines.append("statement %s: %s" % (ov["sentence_id"], ov["sentence"]))
    return "\n".join(lines)


def run_check(args):
    ev = load_events(args.events)
    G = dict(FEEDS)
    for kv in args.G or []:
        k, v = kv.split("=")
        G[k] = int(v)
    unread = {}
    if args.unread:
        with open(args.unread, encoding="utf-8") as f:
            unread = json.load(f)
    feeds = list(G.keys())
    for f in ev:
        if f not in G:
            sys.stderr.write("warning: registration absent feed %s ignores\n" % f)
    results = {}
    for f in feeds:
        if f not in ev:
            sys.stderr.write("warning: feed %s events 0 items. registration 6.4 (sec.) stopped condition applies count exists\n" % f)
        results[f] = summarize_feed(f, ev.get(f, []), G[f], args.start, args.end,
                                    [tuple(x) for x in unread.get(f, [])])
    ov = overall(results, args.api3_g_confirmed)
    print(render(results, ov, args.start, args.end))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fo:
            json.dump({"feeds": results, "overall": ov}, fo, ensure_ascii=False, indent=1)


def run_fetch(args):
    t_from, t_to = args.t_from, args.t_to
    if t_from < WEND and t_to > WSTART and not args.unlock_window:
        sys.stderr.write("refused: request interval registration window and overlaps. results comparison at tier only --unlock-window opens.\n")
        return 2
    rows, rng = fetch_events(args.feeds or list(FEEDS), t_from, t_to, args.out)
    print("event %d items, block %s, call ledger %s" % (len(rows), rng, {"|".join(k): v for k, v in _LEDGER.items()}))
    return 0


# ----------------------------------------------------------------------------
# synthetic test
# ----------------------------------------------------------------------------
def _grid_count(a, b, start=WSTART, end=WEND):
    """(a, b] within window boundary count."""
    cnt = 0
    j0 = max(0, (a - start) // STEP - 1)
    j = j0
    while True:
        t = start + STEP * j
        if t >= end or t > b:
            break
        if t > a:
            cnt += 1
        j += 1
    return cnt


def _series(times, with_round=True, value0=6_000_000_000_000):
    out = []
    for k, t in enumerate(times):
        out.append((t, (1000 + k) if with_round else None, value0 + k))
    return out


def _regular(step, lo=WSTART - 4000, hi=WEND + 4000, offset=0):
    t0 = WSTART + offset
    ts = []
    t = t0 - ((t0 - lo) // step) * step
    while t <= hi:
        ts.append(t)
        t += step
    return ts


def selftest():
    fails = []

    def expect(name, cond, detail=""):
        print(("pass " if cond else "failure ") + name + ((" : " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    # statistics comparison (6.5 (sec.) 3)
    expect("keccak256 empty input", keccak256(b"").hex() ==
           "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
    expect("AnswerUpdated topic",
           keccak256(b"AnswerUpdated(int256,uint256,uint256)").hex() ==
           "0559884fd3a460db3073b7fc896cc77986f16e378210ded43186175bf646fc5f")
    expect("MIN_N 1497", MIN_N == 1497, str(MIN_N))
    expect("n=1728 x=0 upper 0.00173", round(exact_upper0(1728), 5) == 0.00173, "%.6f" % exact_upper0(1728))
    n = 13824
    expect("n=13824 x=0 exact 0.000217", round(exact_upper0(n), 6) == 0.000217 and round(3 / n, 6) == 0.000217)
    expect("CP x=1 0.000343", round(cp_upper(1, n), 6) == 0.000343, "%.6f" % cp_upper(1, n))
    expect("CP x=2 0.000455", round(cp_upper(2, n), 6) == 0.000455, "%.6f" % cp_upper(2, n))
    # registration 5.2 (sec.) boundary count
    xmax_j1 = max(x for x in range(0, 200) if cp_upper(x, n) <= T_LOW)
    xmin_j2 = min(x for x in range(0, 300) if cp_upper(x, n) > T_LOW)
    xmax_j2 = max(x for x in range(0, 300) if cp_upper(x, n) <= T_HIGH)
    xmin_jm = min(x for x in range(1, 300) if cp_lower(x, n) > T_LOW)
    expect("J1 max failure count 18", xmax_j1 == 18, str(xmax_j1))
    expect("J2 start 19", xmin_j2 == 19, str(xmin_j2))
    expect("J2 end 118", xmax_j2 == 118, str(xmax_j2))
    expect("J- start 38", xmin_jm == 38, str(xmin_jm))
    expect("n=1496 x=0  J0", classify(1496, 0)[0] == ["J0"])
    expect("n=1497 x=0  J1", classify(1497, 0)[0] == ["J1"])
    expect("x=19  J2", classify(n, 19)[0] == ["J2"])
    expect("x=38  J2+J-", classify(n, 38)[0] == ["J2", "J-"])

    # synthetic feed
    def run(ev, G, **kw):
        return summarize_feed("T", ev, G, **kw)

    reg = _series(_regular(1200))
    r = run(reg, 1260)
    expect("regular 1200 s: x=0 n=13824 J1", r["x"] == 0 and r["n"] == n and r["verdict"] == "J1")

    # gap one: consecutive two update removes (gap 3600 s)
    ts = _regular(1200)
    k = next(i for i, t in enumerate(ts) if t >= WSTART + 1200 * 100)
    u = ts[k - 1]
    ts2 = ts[:k] + ts[k + 2:]       # u next two items deletion, next update u + 3600
    nxt = ts2[k]
    r = run(_series(ts2), 1260)
    exp = _grid_count(u, nxt)
    expect("gap 3600 s one: failure count", r["x"] == exp and r["fail_runs"] == 1 and r["fail_longest_run"] == exp,
           "x=%d expected %d" % (r["x"], exp))

    # boundary immediately upper: gap 1260 vs 1261
    tj = WSTART + STEP * 500
    uu = tj - 1260

    def around(next_t):
        left = []
        t = uu
        while t > WSTART - 4000:
            left.append(t)
            t -= 600
        right = []
        t = next_t
        while t < WEND + 4000:
            right.append(t)
            t += 600
        return sorted(left) + right
    rA = run(_series(around(tj)), 1260)
    rB = run(_series(around(tj + 1)), 1260)
    expect("gap exactly 1260: failure none", rA["x"] == 0, "x=%d" % rA["x"])
    expect("next update than the boundary 1 s upper(gap 1261): boundary 5 failure", rB["x"] == 5 and
           set(rB["fail_times"]) == {tj - 1200, tj - 900, tj - 600, tj - 300, tj}, "x=%d" % rB["x"])
    # boundary and same time update its boundary as end with in gap falls
    ts3 = _regular(1200)
    expect("boundary and same time update prior in gap falls",
           run(_series(ts3), 1200)["x"] == 0)  # gap 1200 G=1200 is at most, so failure not
    expect("G=1199 if all boundary failure", run(_series(ts3), 1199)["x"] == n)

    # round id missing: update one delete but round id as is keep
    ts = _regular(1200)
    k = next(i for i, t in enumerate(ts) if t >= WSTART + 1200 * 100)
    ev = _series(ts)
    removed = ev.pop(k)
    r = run(ev, 1260)
    exp_p = _grid_count(ts[k - 1], ts[k + 1])
    expect("round id missing: undetermined and failure is not", r["pending"] == exp_p and r["x"] == 0 and r["n"] == n - exp_p,
           "undetermined %d expected %d x=%d" % (r["pending"], exp_p, r["x"]))
    expect("round id missing one items verdict", r["verdict"] == "J1", r["verdict"])
    # same from data round id deleting gap 2400 failure suffices
    ev_nr = [(t, None, v) for (t, _, v) in ev]
    r2 = run(ev_nr, 1260)
    expect("round id if absent check without as gap verdict", r2["pending"] == 0 and r2["x"] == exp_p, "x=%d" % r2["x"])

    # order shuffle and complete duplicate
    import random
    rnd = random.Random(7)
    ev = _series(_regular(1200))
    ev2 = ev + ev[:500]
    rnd.shuffle(ev2)
    r = run(ev2, 1260)
    expect("shuffled order and duplicate event", r["x"] == 0 and r["pending"] == 0)

    # empty feed
    r = run([], 1260)
    expect("empty feed: all failure, J3+J-", r["x"] == n and r["verdict"] == "J3+J-", r["verdict"])

    # window before update none
    first = WSTART + 5000
    ts = [first + 1200 * k for k in range(0, (WEND + 4000 - first) // 1200 + 1)]
    r = run(_series(ts), 1260)
    expect("window prior read interval update none: boundary 17 failure", r["x"] == _grid_count(WSTART - 1, first) == 17,
           "x=%d" % r["x"])

    # window end near: next update none
    last = WEND - 2000
    ts = [t for t in _regular(1200) if t <= WEND - 2000]
    ts.append(last)
    ts = sorted(set(ts))
    r = run(_series(ts), 1260)
    exp_pend = _grid_count(last, last + 1260)
    exp_fail = _grid_count(last + 1260, WEND)
    expect("window end near next update none: limit within undetermined, over failure",
           r["pending"] == exp_pend and r["x"] == exp_fail, "undetermined %d(%d) failure %d(%d)" % (
               r["pending"], exp_pend, r["x"], exp_fail))

    # query failure interval undetermined
    ev = _series(_regular(1200))
    ua = WSTART + 1200 * 50 + 10
    r = run(ev, 1260, unread=[(ua, ua + 100)])
    expect("not read not interval within boundary undetermined", r["x"] == 0 and r["pending"] == _grid_count(
        max(t for t in _regular(1200) if t < ua), min(t for t in _regular(1200) if t >= ua)))

    # API3 type (G = 90000)
    ts = _regular(3600)
    r = run(_series(ts, with_round=False), 90000)
    expect("API3 type regular 3600 s: J1", r["x"] == 0)
    k = next(i for i, t in enumerate(ts) if t >= WSTART + 3600 * 30)
    ts2 = ts[:k] + ts[k + 28:]  # gap 28 * 3600 = 100800 > 90000
    r = run(_series(ts2, with_round=False), 90000)
    exp = _grid_count(ts[k - 1], ts2[k])
    expect("API3 type 100800 s gap: failure count", r["x"] == exp, "x=%d expected %d" % (r["x"], exp))

    # statement test
    def mk(xs, cl_fail_runs=0):
        res = {}
        for f in FEEDS:
            res[f] = {"feed": f, "verdict": xs[f]}
        return res
    allj1 = {f: "J1" for f in FEEDS}
    expect("P2", overall(mk(allj1), True)["sentence_id"] == "P2")
    d = dict(allj1); d["A3-ETHUSD"] = "J2"
    expect("P3", overall(mk(d), True)["sentence_id"] == "P3")
    d = dict(allj1); d["A3-ETHUSD"] = "J2"; d["CL-BTCUSD"] = "J-"
    expect("P4", overall(mk(d), True)["sentence_id"] == "P4")
    expect("C1 (API3 unconfirmed)", overall(mk(d := dict(allj1)), False)["sentence_id"] == "C1")
    d = dict(allj1); d["CL-ETHUSD"] = "J2"
    expect("C2", overall(mk(d), False)["sentence_id"] == "C2")
    d = dict(allj1); d["CL-ETHUSD"] = "J2"; d["CL-BTCUSD"] = "J3"
    expect("C3", overall(mk(d), False)["sentence_id"] == "C3")
    d = dict(allj1); d["CL-ETHUSD"] = "J0"
    expect("J0 feed J1 is not", overall(mk(d), False)["sentence_id"] == "C2")

    # end-to-end: failure 20 items(J2) Chainlink feed making up to statements
    ts = _regular(1200)
    ev = {}
    k = 100
    for _ in range(4):  # gap 3600 (boundary 12) four time
        pass
    ts_f = list(ts)
    # gap 1500 s(boundary 5 about) four place makes
    rm = []
    for base in (100, 400, 700, 1000):
        rm.append(base + 1)
    ts_f = [t for i, t in enumerate(ts) if i not in rm]
    # deleted one items after gap 2400 s. boundary count direct counts.
    exp_total = sum(_grid_count(ts[b], ts[b + 2]) for b in (100, 400, 700, 1000))
    r = run(_series(ts_f), 1260)
    expect("end-to-end: gap four place total failure", r["x"] == exp_total, "x=%d expected %d" % (r["x"], exp_total))
    expect("end-to-end: verdict U is determined", r["verdict"] == ("J1" if cp_upper(exp_total, n) <= T_LOW else "J2"),
           "%s U=%.6f" % (r["verdict"], r["U"]))

    print("\nfailure %d items" % len(fails))
    return 1 if fails else 0


# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="WF1 independent check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--events", required=True)
    c.add_argument("--start", type=int, default=WSTART)
    c.add_argument("--end", type=int, default=WEND)
    c.add_argument("--G", action="append", help="feed=seconds, yes A3-BTCUSD=90000")
    c.add_argument("--unread", help="per feed not read not time interval json {feed: [[a, b], ...]}")
    c.add_argument("--api3-g-confirmed", action="store_true",
                   help="API3 heartbeat seal before confirmed only if gives. if absent C1 onward C3 statement")
    c.add_argument("--json")
    f = sub.add_parser("fetch")
    f.add_argument("--out", required=True)
    f.add_argument("--from", dest="t_from", type=int, required=True)
    f.add_argument("--to", dest="t_to", type=int, required=True)
    f.add_argument("--feeds", nargs="*")
    f.add_argument("--unlock-window", action="store_true",
                   help="registration window and overlapping interval accepts. results comparison at tier only uses")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        run_check(a)
        return 0
    if a.cmd == "fetch":
        return run_fetch(a)
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
