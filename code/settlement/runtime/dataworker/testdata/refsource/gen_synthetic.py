"""Regenerates the synthetic raw replay objects in this directory.

The objects are hand-built to the documented JSON shapes of the Coinbase
Exchange and Kraken public ticker endpoints. They carry no TLS session and are
marked synthetic; they are not captured market data.
"""
import base64, hashlib, json, os
from email.utils import formatdate
OUT=os.path.dirname(os.path.abspath(__file__))
NOTE='synthetic fixture: hand-built to the documented response shape; not captured from the live API'
def req(host, target):
    return (f"GET {target} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: fairbind-refcapture/1\r\n"
            "Accept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n").encode()
def obj(source, url, host, target, date, head_lines, body, status='200 OK', chunked=False):
    date_s=formatdate(date, usegmt=True)
    lines=[f"HTTP/1.1 {status}", f"Date: {date_s}"]+head_lines
    if chunked:
        lines.append("Transfer-Encoding: chunked")
        mid=len(body)//2
        payload=b''.join(b'%x\r\n'%len(p)+p+b'\r\n' for p in (body[:mid],body[mid:]))+b'0\r\n\r\n'
    else:
        lines.append(f"Content-Length: {len(body)}")
        payload=body
    head=("\r\n".join(lines)+"\r\n\r\n").encode()
    raw=head+payload
    b64=lambda b: base64.b64encode(b).decode()
    return {"format":"fairbind/refsource-raw/v1","source_id":source,"method":"GET","url":url,
            "request_raw":b64(req(host,target)),"started_at_unix_ms":date*1000-300,"finished_at_unix_ms":date*1000+120,
            "response_raw":b64(raw),"response_sha256":hashlib.sha256(raw).hexdigest(),"response_head":head.decode(),
            "tls":{"version":"","cipher_suite":"","server_name":"","alpn":"","did_resume":False,"peer_certificates_der":None,
                   "remote_addr":"","verified_chain_root_sha256":""},
            "capture":{"tool":"hand-built","synthetic":True,"note":NOTE}}
def cb(date, price, bid, ask, trade_time, tid, status='200 OK', body=None):
    if body is None:
        body=json.dumps({"ask":ask,"bid":bid,"volume":"8123.40451266","trade_id":tid,"price":price,"size":"0.00213845",
                         "time":trade_time,"rfq_volume":"41.920153","conversions_volume":"0"},separators=(',',':')).encode()
    return obj("coinbase-exchange:ticker:BTC-USD","https://api.exchange.coinbase.com/products/BTC-USD/ticker",
               "api.exchange.coinbase.com","/products/BTC-USD/ticker",date,
               ["Content-Type: application/json; charset=utf-8","Connection: close","Cache-Control: public, max-age=1",
                "Server: cloudflare","CF-Cache-Status: MISS","CF-RAY: 0000000000000000-ICN"],body,status)
def kr(date, body):
    return obj("kraken:ticker:XBTUSD","https://api.kraken.com/0/public/Ticker?pair=XBTUSD","api.kraken.com",
               "/0/public/Ticker?pair=XBTUSD",date,
               ["Content-Type: application/json; charset=utf-8","Connection: close","Server: cloudflare",
                "Strict-Transport-Security: max-age=31536000; includeSubDomains","CF-RAY: 0000000000000001-ICN"],
               body,chunked=True)
def krbody(c,b,a):
    return json.dumps({"error":[],"result":{"XXBTZUSD":{"a":[a,"1","1.000"],"b":[b,"2","2.000"],"c":[c,"0.00150000"],
        "v":["1234.56789012","2345.67890123"],"p":["64101.12345","64052.54321"],"t":[18342,37011],
        "l":["63512.10000","63401.00000"],"h":["64512.00000","64620.30000"],"o":"63904.20000"}}},separators=(',',':')).encode()
T=1790000000
iso=lambda t,frac: __import__('datetime').datetime.fromtimestamp(t,__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+frac+'Z'
files={
 'replay/synthetic-coinbase-btc-usd-1790000000.json': cb(T,"64231.57","64231.56","64231.57",iso(T-1,'.842113'),912345678),
 'replay/synthetic-kraken-xbtusd-1790000001.json': kr(T+1,krbody("64229.80000","64229.70000","64229.80000")),
 'replay/synthetic-coinbase-btc-usd-1789990000.json': cb(T-10000,"63012.01","63012.00","63012.02",iso(T-10002,'.100000'),912300001),
 'malformed/synthetic-kraken-xbtusd-unknown-pair.json': kr(T,b'{"error":["EQuery:Unknown asset pair"]}'),
 'malformed/synthetic-coinbase-btc-usd-503.json': cb(T,"","","","",0,status='503 Service Unavailable',body=b'{"message":"service unavailable"}'),
 'malformed/synthetic-coinbase-btc-usd-duplicate-price.json': cb(T,"","","","",0,body=('{"ask":"64231.57","bid":"64231.56","price":"1","price":"64231.57","time":"%s","trade_id":1}'%iso(T-1,'.5')).encode()),
 'malformed/synthetic-coinbase-btc-usd-exponent.json': cb(T,"6.423157e4","64231.56","64231.57",iso(T-1,'.5'),2),
 'malformed/synthetic-coinbase-btc-usd-old-trade.json': cb(T,"64231.57","64231.56","64231.57",iso(T-3600,'.5'),3),
}
for k,v in files.items():
    p=os.path.join(OUT,k); os.makedirs(os.path.dirname(p),exist_ok=True)
    open(p,'w').write(json.dumps(v,indent=2)+'\n')
print('ok')
