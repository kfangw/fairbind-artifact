"""Builds the adapter fixtures in this directory.

recorded/: seller-role raw objects whose request and response bytes were
captured live by `c1tool capture`. The capture ran through a TLS-terminating
egress proxy, so the recorded certificate chain was the proxy's; it is removed
and the objects are marked synthetic so that Verify accepts them only with
AllowSynthetic. Run with --recorded DIR to convert fresh captures.

synthetic/: hand-built objects to the documented response shapes: error and
rate-limit responses of the seller sources and Bitfinex trade-history pages
(api-pub.bitfinex.com could not be reached from the build environment).
"""
import base64, hashlib, json, os, sys
from email.utils import formatdate

OUT = os.path.dirname(os.path.abspath(__file__))
REC_NOTE = ('response bytes recorded live on 2026-09-30 through a TLS-terminating egress proxy; '
            'the proxy certificate chain was removed')
SYN_NOTE = 'synthetic fixture: hand-built to the documented response shape; not captured from the live API'
b64 = lambda b: base64.b64encode(b).decode()


def convert(path):
    o = json.load(open(path))
    o['tls'] = {"version": "", "cipher_suite": "", "server_name": "", "alpn": "", "did_resume": False,
                "peer_certificates_der": None, "remote_addr": "", "verified_chain_root_sha256": ""}
    o['capture'] = {"tool": o['capture']['tool'], "synthetic": True, "note": REC_NOTE}
    return o


def req(host, target):
    return (f"GET {target} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: fairbind-c1collect/1\r\n"
            "Accept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n").encode()


def obj(source, url, date, body, status='200 OK', ctype='application/json'):
    host = url.split('/')[2]
    target = '/' + url.split('/', 3)[3]
    head = (f"HTTP/1.1 {status}\r\nDate: {formatdate(date, usegmt=True)}\r\nContent-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
    raw = head + body
    return {"format": "fairbind/refsource-raw/v1", "source_id": source, "method": "GET", "url": url,
            "request_raw": b64(req(host, target)), "started_at_unix_ms": date * 1000 - 200,
            "finished_at_unix_ms": date * 1000 + 150, "response_raw": b64(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(), "response_head": head.decode(),
            "tls": {"version": "", "cipher_suite": "", "server_name": "", "alpn": "", "did_resume": False,
                    "peer_certificates_der": None, "remote_addr": "", "verified_chain_root_sha256": ""},
            "capture": {"tool": "hand-built", "synthetic": True, "note": SYN_NOTE}}


BS = ("bitstamp:ticker:btcusd", "https://www.bitstamp.net/api/v2/ticker/btcusd/")
GM = ("gemini:pubticker:btcusd", "https://api.gemini.com/v1/pubticker/btcusd")
BF = "bitfinex:trades:tBTCUSD"
T = 1790000000


def bf_url(start, end):
    return f"https://api-pub.bitfinex.com/v2/trades/tBTCUSD/hist?start={start}&end={end}&sort=-1&limit=100"


def bf(start, end, rows, status='200 OK', raw=None):
    body = raw if raw is not None else json.dumps(rows, separators=(',', ':')).encode()
    return obj(BF, bf_url(start, end), T + 30, body, status, 'application/json; charset=utf-8')


S, E = (T - 10) * 1000, (T + 10) * 1000
synthetic = {
    'bitstamp-429.json': obj(*BS, T, b'{"status":"error","reason":"Rate limit exceeded","code":"API0003"}', '429 Too Many Requests'),
    'bitstamp-exponent.json': obj(*BS, T, b'{"last":"8.5e4","bid":"1","ask":"1","timestamp":"1790000000"}'),
    'gemini-missing-last.json': obj(*GM, T, b'{"bid":"85000.1","ask":"85000.2","volume":{}}'),
    'gemini-duplicate-last.json': obj(*GM, T, b'{"last":"1","last":"85000.1"}'),
    'gemini-503.json': obj(*GM, T, b'{"result":"error"}', '503 Service Unavailable'),
    # Newest first. The nearest trades to T are at T*1000 + 400 and T*1000 - 400.
    'bitfinex-window.json': bf(S, E, [[1005, T * 1000 + 9000, -0.01, 85010.5], [1004, T * 1000 + 400, 0.2, 85003],
                                      [1003, T * 1000 - 400, 0.1, 85001.25], [1002, T * 1000 - 5000, -0.3, 84990]]),
    'bitfinex-empty.json': bf(S, E, []),
    'bitfinex-error.json': bf(S, E, None, raw=b'["error",10020,"limit: invalid"]'),
    'bitfinex-exponent.json': bf(S, E, [[1, T * 1000, 0.1, 8.5e4]], raw=b'[[1,1790000000000,0.1,8.5E4]]'),
    'bitfinex-outside.json': bf(S, E, [[1, E + 1, 0.1, 85000]]),
}


def main():
    os.makedirs(os.path.join(OUT, 'synthetic'), exist_ok=True)
    for name, o in synthetic.items():
        with open(os.path.join(OUT, 'synthetic', name), 'w') as f:
            f.write(json.dumps(o, indent=2) + '\n')
    if len(sys.argv) == 3 and sys.argv[1] == '--recorded':
        os.makedirs(os.path.join(OUT, 'recorded'), exist_ok=True)
        for n in sorted(os.listdir(sys.argv[2])):
            if n.startswith(('bitstamp', 'gemini')) and n.endswith('.json'):
                o = convert(os.path.join(sys.argv[2], n))
                with open(os.path.join(OUT, 'recorded', n.split('-')[0] + '.json'), 'w') as f:
                    f.write(json.dumps(o, indent=2) + '\n')
    print('ok')


if __name__ == '__main__':
    main()
