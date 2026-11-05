"""Read-only public data collection. No signing, payment, or transaction submission."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit


def fetch(url, payload=None):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or parts.username or parts.password:
        raise ValueError('Use a public HTTP(S) URL without embedded credentials')
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=body, headers={'Content-Type': 'application/json'} if body else {})
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as exc:
        response = exc  # A 402 response is itself the public artifact.
    with response:
        return response.status, dict(response.headers), response.read()


def rpc(url, method, params):
    status, _, body = fetch(url, {'jsonrpc':'2.0','id':1,'method':method,'params':params})
    if status != 200:
        raise RuntimeError(f'RPC HTTP status {status}')
    data = json.loads(body)
    if 'error' in data or 'result' not in data:
        raise RuntimeError('RPC returned an error or no result')
    return data['result']


def collect_logs(url, address, start, end, span=1000, topic=None):
    if not (len(address)==42 and address.startswith('0x')):
        raise ValueError('A 20-byte contract address is required')
    int(address[2:],16)
    if start < 0 or end < start or span < 1:
        raise ValueError('Invalid fixed block range')
    if topic is not None:
        if len(topic)!=66 or not topic.startswith('0x'):
            raise ValueError('topic must be 32 bytes')
        int(topic[2:],16)
    chain = rpc(url,'eth_chainId',[])
    pages=[]
    for low in range(start,end+1,span):
        high=min(end,low+span-1)
        query={'address':address,'fromBlock':hex(low),'toBlock':hex(high)}
        if topic is not None: query['topics']=[topic]
        logs=rpc(url,'eth_getLogs',[query])
        if not isinstance(logs,list): raise ValueError('logs must be an array')
        for log in logs:
            if log.get('removed') or log['address'].lower()!=address.lower():
                raise ValueError('Removed log or address mismatch')
            if not low <= int(log['blockNumber'],16) <= high:
                raise ValueError('Log outside requested range')
        pages.append({'from':low,'to':high,'logs':logs})
    # Token events alone do not prove that a payment used x402.
    return {'chainId':chain,'address':address,'start':start,'end':end,
            'topic':topic,'classification':'unclassified-contract-events','pages':pages}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    sub=parser.add_subparsers(dest='kind',required=True)
    page=sub.add_parser('http');page.add_argument('url')
    query=sub.add_parser('rpc');query.add_argument('url')
    query.add_argument('--method',required=True,choices=['eth_chainId','eth_blockNumber','eth_getBlockByNumber'])
    query.add_argument('--params',default='[]')
    logs=sub.add_parser('logs');logs.add_argument('url');logs.add_argument('--address',required=True)
    logs.add_argument('--start',required=True,type=int);logs.add_argument('--end',required=True,type=int)
    logs.add_argument('--span',type=int,default=1000);logs.add_argument('--topic')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():
        raise SystemExit('Commit source changes before collecting result artifacts')
    destination=Path(args.output)
    destination.mkdir(parents=True,exist_ok=False)
    manifest={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
              'upstreams':json.loads((root/'UPSTREAMS.lock.json').read_text()),
              'parameters':vars(args),'seed':None,'grade':'P' if args.kind=='http' else 'M',
              'status':'running'}
    try:
        if args.kind in ('http','rpc'):
            payload=None
            if args.kind=='rpc':
                params=json.loads(args.params)
                if not isinstance(params,list): raise ValueError('RPC parameters must be an array')
                payload={'jsonrpc':'2.0','id':1,'method':args.method,'params':params}
                manifest['request']=payload
            status,headers,raw=fetch(args.url,payload)
            manifest.update(http_status=status,response_headers={k:v for k,v in headers.items() if k.lower() in ('content-type','date','payment-required','cache-control')})
        else:
            raw=json.dumps(collect_logs(args.url,args.address,args.start,args.end,args.span,args.topic),sort_keys=True).encode()
        (destination/'raw.bin').write_bytes(raw)
        manifest.update(status='collected',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        if args.kind=='rpc' and status==200:
            decoded=json.loads(raw)
            manifest['rpc_result_present']='result' in decoded and 'error' not in decoded
    except Exception as exc:
        manifest.update(status='failed',error_type=type(exc).__name__)
        raise
    finally:
        (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
