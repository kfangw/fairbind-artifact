#!/usr/bin/env python3
"""BASE1 measured script (prior registration BASE1_registration.md of implementation). standard library and brotli only uses.

public RPC only uses. key, signature, transaction sending none. read calls only and all call ledger(ledger) counts.

environment variables
  BASE_RPC_URL   default https://mainnet.base.org
  L1_RPC_URL     default https://ethereum-rpc.publicnode.com
  BLOBSCAN_URL   default https://api.blobscan.com
  BLOCKSCOUT_URL default https://eth.blockscout.com
  BEACON_URL     default https://ethereum-beacon-api.publicnode.com (recent about 18 days blob only)

sub command
  probe        three kind call only whether it works checks(statistics none).
  live         optimism_syncStatus(or tag three time call) fixed at intervals calls jsonl recorded.
  l1-batches   batcher batch inbox going L1 transaction list jsonl recorded(source rpc or blockscout).
  decode       l1-batches output from the transactions blob takes frame, channel, batch decode per channel L2 interval recorded.
  gaps         l1-batches from the output threshold or more posting spacing list recorded.
  dtx-auth     transaction hash sample transferWithAuthorization input decode signature time proxy and included block time difference recorded.
  judge        registration 6 (sec.) verdict rules episodes.jsonl and channel jsonl mechanically applies.
  small        small interval test: L2 block interval one for header linearity check, L1 batch find, blob decoding one pass run
               per line records only outputs(summary statistics none).
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

BASE_RPC = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
L1_RPC = os.environ.get("L1_RPC_URL", "https://ethereum-rpc.publicnode.com")
BLOBSCAN = os.environ.get("BLOBSCAN_URL", "https://api.blobscan.com")
BLOCKSCOUT = os.environ.get("BLOCKSCOUT_URL", "https://eth.blockscout.com")
BEACON = os.environ.get("BEACON_URL", "https://ethereum-beacon-api.publicnode.com")

# registration 3.1 (sec.) fixed values
L2_GENESIS_TS = 1686789347          # Base mainnet L2 genesis time, block n time = this value + 2n
L2_BLOCK_TIME = 2
BATCHER = "0x5050f69a9786f081509234f1a7f4684b5e5b76c9"
INBOX = "0xff00000000000000000000000000000000008453"
L1_GENESIS_TS = 1606824023          # Ethereum beacon chain genesis, slot = (ts - this value) / 12
SEL_TWA = "e3ee160e"                # transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)
SEL_TWA_BYTES = "cf092995"          # same name, last arguments bytes signature

LEDGER = {}


def count(host, method, ok=True):
    k = f"{host}|{method}|{'ok' if ok else 'fail'}"
    LEDGER[k] = LEDGER.get(k, 0) + 1


def http(url, data=None, headers=None, timeout=60, tries=6, host=None, method="GET"):
    """retry(exponential backoff) with HTTP. failures in the ledger counts. finally within if exception."""
    h = {"user-agent": "base1-measure/1", "accept": "*/*"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            count(host or url, method, True)
            return body
        except urllib.error.HTTPError as e:
            last = e
            count(host or url, method, False)
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** i))
                continue
            raise
        except Exception as e:  # time over, connection error
            last = e
            count(host or url, method, False)
            time.sleep(min(60, 2 ** i))
    raise RuntimeError(f"request failure {url}: {last}")


def rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    raw = http(url, data=body, headers={"content-type": "application/json"}, host=url, method=method)
    r = json.loads(raw)
    if "error" in r:
        raise RuntimeError(f"{method} error: {r['error']}")
    return r["result"]


def hx(v):
    return int(v, 16)


def l2_block(n):
    r = rpc(BASE_RPC, "eth_getBlockByNumber", [n if isinstance(n, str) else hex(n), False])
    return r


def l1_block(n, full=False):
    return rpc(L1_RPC, "eth_getBlockByNumber", [n if isinstance(n, str) else hex(n), full])


def l1_block_at_or_after(ts):
    """time ts at least first L1 block number(binary search, headers only)."""
    hi = hx(l1_block("latest")["number"])
    lo = max(0, hi - int((time.time() - ts) / 12) - 5000)
    lo = max(0, min(lo, hi))
    while hx(l1_block(lo)["timestamp"]) >= ts and lo > 0:
        lo = max(0, lo - 20000)
    while lo < hi:
        mid = (lo + hi) // 2
        if hx(l1_block(mid)["timestamp"]) >= ts:
            hi = mid
        else:
            lo = mid + 1
    return lo


def write_ledger(path):
    if path:
        with open(path, "w") as f:
            json.dump(dict(sorted(LEDGER.items())), f, ensure_ascii=False, indent=1)
    print("call ledger:", json.dumps(dict(sorted(LEDGER.items())), ensure_ascii=False), file=sys.stderr)


# ---------------------------------------------------------------- probe, live

def cmd_probe(a):
    out = {}
    out["base_latest"] = hx(l2_block("latest")["number"])
    for tag in ("safe", "finalized"):
        out["base_" + tag] = hx(l2_block(tag)["number"])
    try:
        s = rpc(BASE_RPC, "optimism_syncStatus", [])
        out["syncStatus_keys"] = sorted(s.keys())
    except Exception as e:
        out["syncStatus"] = f"within ok: {e}"
    out["l1_latest"] = hx(l1_block("latest")["number"])
    try:
        out["blobscan_ok"] = bool(http(f"{BLOBSCAN}/blocks?limit=1", host=BLOBSCAN))
    except Exception as e:
        out["blobscan_ok"] = f"within ok: {e}"
    print(json.dumps(out, ensure_ascii=False, indent=1))


def sample_live():
    t0 = time.time()
    try:
        s = rpc(BASE_RPC, "optimism_syncStatus", [])
        rec = {
            "src": "syncStatus",
            "unsafe": s["unsafe_l2"]["number"], "unsafe_ts": s["unsafe_l2"]["timestamp"],
            "safe": s["safe_l2"]["number"], "safe_ts": s["safe_l2"]["timestamp"],
            "finalized": s["finalized_l2"]["number"], "finalized_ts": s["finalized_l2"]["timestamp"],
            "current_l1": s["current_l1"]["number"], "current_l1_ts": s["current_l1"]["timestamp"],
            "head_l1": s["head_l1"]["number"], "head_l1_ts": s["head_l1"]["timestamp"],
        }
    except Exception:
        rec = {"src": "tags"}
        for k, tag in (("unsafe", "latest"), ("safe", "safe"), ("finalized", "finalized")):
            b = l2_block(tag)
            rec[k], rec[k + "_ts"] = hx(b["number"]), hx(b["timestamp"])
    rec["local_time"] = round(t0, 3)
    return rec


def cmd_live(a):
    with open(a.out, "a") as f:
        for i in range(a.samples):
            try:
                rec = sample_live()
            except Exception as e:
                rec = {"error": str(e), "local_time": round(time.time(), 3)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if i + 1 < a.samples:
                time.sleep(a.interval)


# ---------------------------------------------------------------- Stage A: l1-batches

def tx_row(t, block):
    return {
        "l1_block": hx(block["number"]), "l1_time": hx(block["timestamp"]), "hash": t["hash"],
        "tx_index": hx(t["transactionIndex"]), "type": hx(t.get("type", "0x0")),
        "blob_hashes": t.get("blobVersionedHashes", []),
        "calldata_len": (len(t.get("input", "0x")) - 2) // 2,
    }


def scan_rpc(l1_from, l1_to):
    rows = []
    for n in range(l1_from, l1_to + 1):
        b = l1_block(n, True)
        for t in b["transactions"]:
            if t["from"].lower() == BATCHER and (t.get("to") or "").lower() == INBOX:
                rows.append(tx_row(t, b))
    return rows


def scan_blockscout(ts_from, ts_to, max_pages, seed_block=None):
    """Blockscout address transaction list from the latest back walking [ts_from, ts_to) within transactions collects."""
    rows, pages = [], 0
    params = {"block_number": seed_block, "index": 100000, "items_count": 50} if seed_block else {}
    while pages < max_pages:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{BLOCKSCOUT}/api/v2/addresses/{BATCHER}/transactions" + (f"?{q}" if q else "")
        d = json.loads(http(url, host=BLOCKSCOUT, method="addr_txs"))
        pages += 1
        stop = False
        for i in d["items"]:
            ts = int(time.mktime(time.strptime(i["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))) - time.timezone
            if ts >= ts_to:
                continue
            if ts < ts_from:
                stop = True
                break
            if (i.get("to") or {}).get("hash", "").lower() != INBOX:
                continue
            rows.append({"l1_block": i["block_number"], "l1_time": ts, "hash": i["hash"],
                         "tx_index": i["position"], "type": i["type"],
                         "blob_hashes": i.get("blob_versioned_hashes") or [], "calldata_len": None})
        npp = d.get("next_page_params")
        if stop or not npp:
            break
        params = npp
    return rows


def cmd_l1_batches(a):
    if a.source == "rpc":
        n0 = l1_block_at_or_after(a.ts_from)
        n1 = l1_block_at_or_after(a.ts_to) - 1
        rows = scan_rpc(n0, n1)
    else:
        rows = scan_blockscout(a.ts_from, a.ts_to, a.max_pages, l1_block_at_or_after(a.ts_to) if a.seed else None)
    rows.sort(key=lambda r: (r["l1_block"], r["tx_index"]))
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"transaction {len(rows)} items record", file=sys.stderr)


def cmd_gaps(a):
    rows = [json.loads(l) for l in open(a.inp)]
    times = sorted({(r["l1_block"], r["l1_time"]) for r in rows})
    with open(a.out, "w") as f:
        for (b0, t0), (b1, t1) in zip(times, times[1:]):
            if t1 - t0 >= a.min_seconds:
                f.write(json.dumps({"l1_block_before": b0, "t_before": t0, "l1_block_after": b1,
                                    "t_after": t1, "gap_seconds": t1 - t0, "gap_l2_blocks": (t1 - t0) // L2_BLOCK_TIME}) + "\n")


# ---------------------------------------------------------------- blob -> frames -> channels -> batches

def blob_bytes(vh, l1_time, tries_beacon=True):
    """blob bytes(131072). if recent beacon, otherwise Blobscan pointing to archive."""
    info = json.loads(http(f"{BLOBSCAN}/blobs/{vh}", host=BLOBSCAN, method="blobs"))
    for ref in info.get("dataStorageReferences", []):
        url = ref.get("url")
        if not url:
            continue
        try:
            b = http(url, host="blob-storage:" + ref.get("storage", "?"), method="download", timeout=120)
            if len(b) == 131072:
                return b, ref.get("storage")
        except Exception:
            continue
    raise RuntimeError(f"blob from the archive not fetched cannot {vh}")


def blob_to_data(b):
    """OP Stack blob encoding v0 decodes(op-node blob.go ToData)."""
    if len(b) != 131072 or b[1] != 0:
        raise ValueError("blob version or length")
    length = (b[2] << 16) | (b[3] << 8) | b[4]
    if length > 130044:
        raise ValueError("blob length field")
    out = bytearray(131072)
    out[0:27] = b[5:32]
    opos, ipos = 28, 32
    enc = [0, 0, 0, 0]
    enc[0] = b[0]

    def dfe(opos, ipos):
        if b[ipos] & 0xC0:
            raise ValueError("field element top bit")
        out[opos:opos + 31] = b[ipos + 1:ipos + 32]
        return b[ipos], opos + 32, ipos + 32

    def reassemble(opos):
        opos -= 1
        x = (enc[0] & 0x3F) | ((enc[1] & 0x30) << 2)
        y = (enc[1] & 0x0F) | ((enc[3] & 0x0F) << 4)
        z = (enc[2] & 0x3F) | ((enc[3] & 0x30) << 2)
        out[opos - 32 * 3] = x
        out[opos - 32 * 2] = y
        out[opos - 32 * 1] = z
        return opos

    for i in range(1, 4):
        enc[i], opos, ipos = dfe(opos, ipos)
    opos = reassemble(opos)
    i = 1
    while i < 1024 and opos < length:
        for j in range(4):
            enc[j], opos, ipos = dfe(opos, ipos)
        opos = reassemble(opos)
        i += 1
    return bytes(out[:length])


def parse_frames(data):
    if not data or data[0] != 0:
        raise ValueError("derivation version")
    p, frames = 1, []
    while p < len(data):
        if p + 23 > len(data):
            raise ValueError("frame header truncated")
        cid = data[p:p + 16]
        num = struct.unpack(">H", data[p + 16:p + 18])[0]
        ln = struct.unpack(">I", data[p + 18:p + 22])[0]
        body = data[p + 22:p + 22 + ln]
        if len(body) != ln or p + 22 + ln + 1 > len(data):
            raise ValueError("frame body truncated")
        last = data[p + 22 + ln]
        if last not in (0, 1):
            raise ValueError("is_last")
        frames.append((cid, num, body, last))
        p += 22 + ln + 1
    return frames


def uvarint(buf, p):
    x, s = 0, 0
    while True:
        c = buf[p]
        p += 1
        x |= (c & 0x7F) << s
        if c < 0x80:
            return x, p
        s += 7


def rlp_next(buf, p):
    """RLP item one (kind, body start, body end, next position). kind 'S' string, 'L' list."""
    c = buf[p]
    if c < 0x80:
        return "S", p, p + 1, p + 1
    if c <= 0xB7:
        n = c - 0x80
        return "S", p + 1, p + 1 + n, p + 1 + n
    if c <= 0xBF:
        ll = c - 0xB7
        n = int.from_bytes(buf[p + 1:p + 1 + ll], "big")
        return "S", p + 1 + ll, p + 1 + ll + n, p + 1 + ll + n
    if c <= 0xF7:
        n = c - 0xC0
        return "L", p + 1, p + 1 + n, p + 1 + n
    ll = c - 0xF7
    n = int.from_bytes(buf[p + 1:p + 1 + ll], "big")
    return "L", p + 1 + ll, p + 1 + ll + n, p + 1 + ll + n


def decompress_channel(raw):
    b0 = raw[0]
    if (b0 & 0x0F) == 8 and (b0 >> 4) <= 7:
        d = zlib.decompressobj()
        return d.decompress(raw)
    if b0 == 1:
        import brotli
        return brotli.decompress(raw[1:])
    raise ValueError("channel compression format")


def channel_batches(stream):
    """channel stream batch (plural) L2 time interval collects. returns: (first time, last time, block count, per kind batch count)."""
    p, ts_first, ts_last, nblocks, kinds = 0, None, None, 0, {}
    while p < len(stream):
        kind, s, e, nxt = rlp_next(stream, p)
        if kind != "S":
            raise ValueError("batch RLP must be a string must")
        bt = stream[s:e]
        p = nxt
        if not bt:
            continue
        t = bt[0]
        kinds[t] = kinds.get(t, 0) + 1
        if t == 0:      # singular: [parent, epoch_num, epoch_hash, timestamp, txs]
            k, s2, e2, _ = rlp_next(bt, 1)
            q = s2
            items = []
            for _ in range(4):
                kk, a1, b1, q = rlp_next(bt, q)
                items.append(int.from_bytes(bt[a1:b1], "big"))
            ts = items[3]
            lo = hi = ts
            n = 1
        elif t == 1:    # span: rel_timestamp, l1_origin_num, parent_check(20), l1_origin_check(20), block_count
            rel, q = uvarint(bt, 1)
            _, q = uvarint(bt, q)
            q += 40
            n, q = uvarint(bt, q)
            lo = L2_GENESIS_TS + rel
            hi = lo + (n - 1) * L2_BLOCK_TIME
        else:
            continue
        ts_first = lo if ts_first is None else min(ts_first, lo)
        ts_last = hi if ts_last is None else max(ts_last, hi)
        nblocks += n
    return ts_first, ts_last, nblocks, kinds


def decode_txs(txs, out_path=None, only_complete_in=None, cache=None):
    """txs: l1-batches rows list(in time order). channels assembles per channel records returns.
    only_complete_in = (t0, t1): last frame this time interval L1 block within channels only returns."""
    chans = {}   # cid -> {frames: {num: body}, last_num, complete_l1 (block, time)}
    fail = []
    for r in txs:
        if not r["blob_hashes"]:
            fail.append({"hash": r["hash"], "blob": None, "error": "calldata_tx_not_decoded"})
        for vh in r["blob_hashes"]:
            try:
                b, storage = blob_bytes(vh, r["l1_time"])
                fr = parse_frames(blob_to_data(b))
            except Exception as e:
                fail.append({"hash": r["hash"], "blob": vh, "error": str(e)})
                continue
            for cid, num, body, last in fr:
                c = chans.setdefault(cid, {"frames": {}, "last_num": None, "last_at": None, "first_at": None})
                c["frames"][num] = body
                if c["first_at"] is None or (r["l1_block"], r["l1_time"]) < c["first_at"]:
                    c["first_at"] = (r["l1_block"], r["l1_time"])
                if last:
                    c["last_num"] = num
                    c["last_at"] = (r["l1_block"], r["l1_time"])
        # calldata transaction(blob none) this in the implementation not handled not. registration 3.4 (sec.): measured in the period all blob.
    out = []
    for cid, c in chans.items():
        rec = {"channel_id": cid.hex(), "frames": len(c["frames"])}
        if c["last_num"] is None or set(c["frames"]) != set(range(c["last_num"] + 1)):
            rec["status"] = "incomplete"
            out.append(rec)
            continue
        if only_complete_in and not (only_complete_in[0] <= c["last_at"][1] < only_complete_in[1]):
            continue
        try:
            raw = b"".join(c["frames"][i] for i in range(c["last_num"] + 1))
            ts0, ts1, nb, kinds = channel_batches(decompress_channel(raw))
            rec.update({"status": "ok", "l2_ts_first": ts0, "l2_ts_last": ts1, "l2_blocks": nb,
                        "l2_first": (ts0 - L2_GENESIS_TS) // L2_BLOCK_TIME if ts0 is not None else None,
                        "l2_last": (ts1 - L2_GENESIS_TS) // L2_BLOCK_TIME if ts1 is not None else None,
                        "batch_kinds": kinds,
                        "l1_complete_block": c["last_at"][0], "l1_complete_time": c["last_at"][1],
                        "l1_first_block": c["first_at"][0],
                        "lag_seconds": c["last_at"][1] - ts1 if ts1 is not None else None})
        except Exception as e:
            rec.update({"status": "decode_error", "error": str(e)})
        out.append(rec)
    # previous channel(l2_first this channel l2_first - 1  continuing one) if present new safe becoming just before safe head age recorded.
    by_last = {r["l2_last"]: r for r in out if r.get("status") == "ok" and r.get("l2_last") is not None}
    for r in out:
        if r.get("status") == "ok" and r.get("l2_first") is not None:
            prev = by_last.get(r["l2_first"] - 1)
            if prev is not None:
                r["safe_age_peak_seconds"] = r["l1_complete_time"] - prev["l2_ts_last"]
            else:
                r["safe_age_peak_seconds"] = None
    return out, fail


def cmd_decode(a):
    rows = [json.loads(l) for l in open(a.inp)]
    t0, t1 = a.slice_from, a.slice_to
    sel = [r for r in rows if t0 - a.pad <= r["l1_time"] < t1]
    out, fail = decode_txs(sel, only_complete_in=(t0, t1))
    with open(a.out, "a") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    if fail:
        with open(a.out + ".fail", "a") as f:
            for r in fail:
                f.write(json.dumps(r) + "\n")
    print(f"channel {len(out)} items, blob failure {len(fail)} items", file=sys.stderr)


# ---------------------------------------------------------------- d_tx: x402 authorization

def decode_twa(inp):
    h = inp[2:] if inp.startswith("0x") else inp
    for sel, tag in ((SEL_TWA, "direct"), (SEL_TWA_BYTES, "direct_bytes")):
        i = h.find(sel)
        if i < 0:
            continue
        body = h[i + 8:]
        if len(body) < 64 * 6:
            continue
        w = [int(body[k * 64:(k + 1) * 64], 16) for k in range(6)]
        mode = tag if i == 0 else "embedded"
        return {"from": "0x" + body[24:64], "to": "0x" + body[64 + 24:128],
                "value": w[2], "valid_after": w[3], "valid_before": w[4], "nonce": "0x" + body[320:384], "mode": mode}
    return None


def sample_hashes(globs, n, seed):
    import csv
    import glob
    hs = {}
    for g in globs:
        for fn in sorted(glob.glob(g)):
            op = gzip.open if fn.endswith(".gz") else open
            with op(fn, "rt") as f:
                for row in csv.DictReader(f):
                    hs[row["tx_hash"]] = row["block_time_utc"]
    ranked = sorted(hs, key=lambda h: hashlib.sha256((seed + h).encode()).hexdigest())
    return ranked[:n]


def cmd_dtx_auth(a):
    hashes = sample_hashes(a.glob, a.n, a.seed)
    with open(a.out, "w") as f:
        for h in hashes:
            rec = {"tx_hash": h}
            try:
                t = rpc(BASE_RPC, "eth_getTransactionByHash", [h])
                if not t or not t.get("blockNumber"):
                    rec["status"] = "missing"
                else:
                    bn = hx(t["blockNumber"])
                    rec["block"] = bn
                    rec["block_time"] = L2_GENESIS_TS + L2_BLOCK_TIME * bn   # linear time(registration G1 (c)). header check small
                    d = decode_twa(t["input"])
                    if d is None:
                        rec["status"] = "not_twa"
                        rec["selector"] = t["input"][:10]
                    else:
                        rec["status"] = "ok"
                        rec.update(d)
                        rec["timeout"] = d["valid_before"] - d["valid_after"] - 600
                        rec["sign_time_proxy"] = d["valid_after"] + 600
                        rec["d_auth_seconds"] = rec["block_time"] - rec["sign_time_proxy"]
            except Exception as e:
                rec["status"] = "rpc_error"
                rec["error"] = str(e)
            f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------- judge (registration 6 (sec.))

EVENT_S = 300       # registration 2.1 (sec.): stopped event lower(seconds)
CADENCE_S = 60      # d_inc 30 block
T_P_S = 3600        # T_p 1,800 block
S_OBS_S = 43200     # d_obs,S 21,600 block


def binom_cdf(k, n, p):
    from math import lgamma, log, exp
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    tot = 0.0
    for i in range(0, k + 1):
        tot += exp(lgamma(n + 1) - lgamma(i + 1) - lgamma(n - i + 1) + i * log(p) + (n - i) * log(1 - p))
    return min(1.0, tot)


def clopper_pearson(k, n, alpha=0.05):
    """exact both sides (1-alpha) interval. bisection."""
    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) <= alpha / 2)
    return lower, upper


def cmd_judge(a):
    """registration 6 (sec.) quantity counts. grade and statement a reader 6section and 7never chooses."""
    gaps = [json.loads(l) for l in open(a.gaps)] if a.gaps else []
    chans = [json.loads(l) for l in open(a.channels)] if a.channels else []
    ps, pe = a.period_start, a.period_end
    res = {"period_days": (pe - ps) / 86400}
    ev = [g for g in gaps if g["gap_seconds"] >= EVENT_S]
    res["E_60"] = sum(1 for g in gaps if CADENCE_S <= g["gap_seconds"] < EVENT_S)   # gaps file 300 s only at least if containing 0
    res["E_300"] = {"n": len(ev), "sum_s": sum(g["gap_seconds"] for g in ev), "max_s": max((g["gap_seconds"] for g in ev), default=0)}
    tp = [g for g in ev if g["gap_seconds"] >= T_P_S]
    res["E_Tp"] = {"n": len(tp), "sum_s": sum(g["gap_seconds"] for g in tp), "max_s": max((g["gap_seconds"] for g in tp), default=0)}
    res["E_S"] = sum(1 for g in ev if g["gap_seconds"] >= S_OBS_S)
    res["X_Tp_s"] = sum(max(0, g["gap_seconds"] - T_P_S) for g in ev)
    n_h = int((pe - ps) // 3600)
    hit = set()
    for g in ev:
        lo, hi = g["t_before"], g["t_before"] + g["gap_seconds"] - T_P_S    # risk time [lo, hi)
        if hi <= lo:
            continue
        for h in range(max(0, int((lo - ps) // 3600)), int((hi - ps) // 3600) + 1):
            if ps + h * 3600 < hi and ps + (h + 1) * 3600 > lo and 0 <= h < n_h:
                hit.add(h)
    k_h = len(hit)
    res["slots"] = {"n_h": n_h, "k_h": k_h}
    if k_h == 0:
        res["upper95_share_of_hours"] = 3.0 / n_h
    else:
        lo_, hi_ = clopper_pearson(k_h, n_h)
        res["share_of_hours_ci95"] = [lo_, hi_]
    res["X_Tp_share_of_time"] = res["X_Tp_s"] / (pe - ps)
    ok = [c for c in chans if c.get("status") == "ok"]
    pk = [c["safe_age_peak_seconds"] for c in ok if c.get("safe_age_peak_seconds") is not None]
    res["P_c"] = {"channels_total": len(chans), "ok": len(ok), "missing_peak": len(ok) - len(pk),
                  "ge_30_blocks": sum(1 for x in pk if x >= CADENCE_S), "ge_1800_blocks": sum(1 for x in pk if x >= T_P_S),
                  "ge_21600_blocks": sum(1 for x in pk if x >= S_OBS_S)}
    if pk:
        v = sorted(pk)
        q = lambda f: v[min(len(v) - 1, int(f * len(v)))] / 2.0
        res["P_c"].update({"p50_blocks": q(0.5), "p90_blocks": q(0.9), "p99_blocks": q(0.99), "p999_blocks": q(0.999), "max_blocks": v[-1] / 2.0})
    print(json.dumps(res, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- small: small interval test

def cmd_small(a):
    n0, n1 = a.l2_start, a.l2_start + a.l2_count - 1
    print(f"# small: L2 {n0}..{n1}, default RPC {BASE_RPC}, L1 {L1_RPC}")
    bad = 0
    t_first = t_last = None
    for n in range(n0, n1 + 1):
        b = l2_block(n)
        ts = hx(b["timestamp"])
        lin = L2_GENESIS_TS + L2_BLOCK_TIME * n
        if ts != lin:
            bad += 1
        t_first = ts if t_first is None else t_first
        t_last = ts
        print(f"L2 {n} ts={ts} linear_ok={ts == lin}")
    print(f"# linearity mismatch {bad} items / {a.l2_count}")
    # interval last block containing channel L1 entered time finds: last time after L1 block scans.
    start_l1 = l1_block_at_or_after(t_last)
    end_l1 = start_l1 + a.scan_l1
    print(f"# L1 {start_l1}..{end_l1} at batcher transactions finds")
    rows = scan_rpc(start_l1, end_l1)
    for r in rows:
        print("L1tx", json.dumps({k: r[k] for k in ("l1_block", "l1_time", "hash", "tx_index")}), "blobs", len(r["blob_hashes"]))
    # blob decode interval covering channels finds(channel previous in transactions started count so prior L1 block also scans)
    pre = scan_rpc(max(0, start_l1 - a.pre_l1), start_l1 - 1)
    allrows = sorted(pre + rows, key=lambda r: (r["l1_block"], r["tx_index"]))
    recs, fail = decode_txs(allrows[: a.max_txs])
    for r in recs:
        covers = (r.get("status") == "ok" and r["l2_ts_first"] <= t_last and r["l2_ts_last"] >= t_first)
        print("channel", json.dumps({k: r.get(k) for k in ("channel_id", "status", "frames", "l2_first", "l2_last", "l2_blocks", "l1_complete_block", "l1_complete_time", "lag_seconds", "safe_age_peak_seconds", "error")}), "covers_range", covers)
    for f_ in fail:
        print("blob_fail", json.dumps(f_))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=None, help="call ledger to use json path")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("probe")
    p = sp.add_parser("live"); p.add_argument("--samples", type=int, default=3); p.add_argument("--interval", type=float, default=10); p.add_argument("--out", required=True)
    p = sp.add_parser("l1-batches"); p.add_argument("--source", choices=["rpc", "blockscout"], default="blockscout")
    p.add_argument("--ts-from", type=int, required=True); p.add_argument("--ts-to", type=int, required=True)
    p.add_argument("--max-pages", type=int, default=100000); p.add_argument("--seed", action="store_true", help="ts-to side L1 block list start(its after side skipped)"); p.add_argument("--out", required=True)
    p = sp.add_parser("gaps"); p.add_argument("--in", dest="inp", required=True); p.add_argument("--min-seconds", type=int, default=120); p.add_argument("--out", required=True)
    p = sp.add_parser("decode"); p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--slice-from", type=int, required=True); p.add_argument("--slice-to", type=int, required=True)
    p.add_argument("--pad", type=int, default=600); p.add_argument("--out", required=True)
    p = sp.add_parser("dtx-auth"); p.add_argument("--glob", action="append", required=True); p.add_argument("--n", type=int, default=2000)
    p.add_argument("--seed", default="BASE1"); p.add_argument("--out", required=True)
    p = sp.add_parser("judge"); p.add_argument("--gaps"); p.add_argument("--channels")
    p.add_argument("--period-start", type=int, required=True); p.add_argument("--period-end", type=int, required=True)
    p = sp.add_parser("small"); p.add_argument("--l2-start", type=int, required=True); p.add_argument("--l2-count", type=int, default=100)
    p.add_argument("--scan-l1", type=int, default=40); p.add_argument("--pre-l1", type=int, default=12); p.add_argument("--max-txs", type=int, default=40)
    a = ap.parse_args()
    try:
        {"probe": cmd_probe, "live": cmd_live, "l1-batches": cmd_l1_batches, "gaps": cmd_gaps, "decode": cmd_decode,
         "dtx-auth": cmd_dtx_auth, "judge": cmd_judge, "small": cmd_small}[a.cmd](a)
    finally:
        write_ledger(a.ledger)


if __name__ == "__main__":
    main()
