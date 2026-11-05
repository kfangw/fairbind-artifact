#!/usr/bin/env python3
"""Supplement tools (2026-10-07). Decode Dune tool-result JSON files for
 - S1-b v2 extraction (query 8907656): packed settlements -> settlements_<date>.csv.gz (same bytes layout as tool/decode.py)
 - S1-a supplement (query 8907660): final CSV lines per kind
Prints only counts, sums, hashes."""
import sys, json, glob, os, base64, gzip, hashlib, io, datetime
FAC="""0x14fda13953fc30428938e6bf950d036e77214e52 0x2a89407a98a0732b7fd578c4e156b7166540eb5a 0x42dd53906b49c202e8e934b059dc019e04634b00 0x4c934c63c786157fefd990945b25ea60a0fb0205 0x59b7ebc67a3d627fabaf06768c818638452ae704 0x625d8a65134079f8faaac39a7947c73d93c6ac39 0x64cc42b1ce598e3abcfbb64df4688521ddbf1f0a 0x67b9ce703d9ce658d7c4ac3c289cea112fe662af 0x68a96f41ff1e9f2e7b591a931a4ad224e7c07863 0x68efafe862d89ce66dd3d7b07d5a3747a0871164 0x772003a2e9c2ccc8af956870a37a66f64f8cec38 0x8cda367232d78c067116e3260da881d2da8ffa39 0x8f5cb67b49555e614892b7233cfddebfb746e531 0x93f6601151ccb08f333ab4b1cccfb1e188c0be44 0x97acce27d5069544480bde0f04d9f47d7422a016 0xa32ccda98ba7529705a059bd2d213da8de10d101 0xb87e1a2cc2b4643f2892768e80e41167f17c5860 0xca5e87f82b3fa093800e6ad67d621a427d79c70d 0xe72f0af4cf41356d433723547f1412ca27fbb1b8 0xe74817f4cdc15844314812b2271276e64e890fae""".split()
HDR='block_number,block_time_utc,tx_hash,tx_index,trace_address,recipient,payer,value_atomic,facilitator\n'
EDGES=[1000,10000,20000,50000,100000,200000,500000,1000000,10000000,100000000,'inf']
def load_files(files):
    """Return (rows, total, exec_id, cost) merged over files of one execution (either tool shape)."""
    rows=[]; total=None; ex=None; cost=None
    for f in files:
        d=json.load(open(f))
        rp=d.get('result_preview',d)
        assert rp['state'].endswith('COMPLETED'),rp['state']
        e=rp['executionId']; assert ex in (None,e),('mixed executions',ex,e); ex=e
        total=rp['resultMetadata']['totalRowCount']; cost=rp['resultMetadata'].get('executionCostCredits',cost)
        rows+=rp['data']['rows']
    return rows,total,ex,cost
def decode_settlements(files,out):
    rows,total,ex,cost=load_files(files); os.makedirs(out,exist_ok=True)
    chunks={(r['d'],int(r['ck'])):r for r in rows}
    assert len(chunks)==total,('incomplete',len(chunks),total)
    recs=[]
    for day in sorted({k[0] for k in chunks}):
        cks=sorted(k[1] for k in chunks if k[0]==day); assert cks==list(range(len(cks))),('gap',day)
        hu=hashlib.sha256(); hu.update(HDR.encode()); raw=io.BytesIO()
        gz=gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=6,mtime=0); gz.write(HDR.encode())
        n=sv=s_bn=s_ti=s_t=s_h=s_r=s_p=s_f=s_tr=0; prev=None; ubytes=len(HDR)
        for ck in cks:
            r=chunks[(day,ck)]; lines=r['lines'].split('\n')
            assert len(lines)==int(r['n']),('n',day,ck)
            if ck<len(cks)-1: assert len(lines)==500,('short',day,ck)
            bn0=int(r['bn0']); t0=int(float(r['t0'])); bn1=int(r['bn1']); t1=int(float(r['t1']))
            assert t1==t0+2*(bn1-bn0),('time formula',day,ck)
            csum=0; buf=[]
            for ln in lines:
                bn,ti,h,rc,p,v,fi,tr=ln.split(',')
                bn=int(bn); ti_=int(ti); v_=int(v); fi=int(fi)
                key=(bn,ti_,tr); assert prev is None or key>prev,('order',day,ck); prev=key
                t=t0+2*(bn-bn0)
                hb=base64.b64decode(h); rb=base64.b64decode(rc); pb=base64.b64decode(p)
                assert len(hb)==32 and len(rb)==20 and len(pb)==20
                ts=datetime.datetime.utcfromtimestamp(t); assert ts.strftime('%Y-%m-%d')==day,('date',day,ck)
                buf.append(f"{bn},{ts.strftime('%Y-%m-%d %H:%M:%S')},0x{hb.hex()},{ti_},{tr},0x{rb.hex()},0x{pb.hex()},{v_},{FAC[fi]}\n")
                n+=1; sv+=v_; csum+=v_; s_bn+=bn; s_ti+=ti_; s_t+=t; s_f+=fi
                s_h+=int.from_bytes(hb[:4],'big'); s_r+=int.from_bytes(rb[:4],'big'); s_p+=int.from_bytes(pb[:4],'big')
                s_tr+=(0 if tr=='' else tr.count('.')+1)
            assert csum==int(r['sv']),('chunk sum',day,ck)
            b=''.join(buf).encode(); gz.write(b); hu.update(b); ubytes+=len(b)
        gz.close(); data=raw.getvalue(); fn=f'settlements_{day}.csv.gz'
        open(os.path.join(out,fn),'wb').write(data)
        rec=dict(file=fn,date=day,rows=n,value_sum_atomic=str(sv),sha256_csv=hu.hexdigest(),bytes_csv=ubytes,sha256_gz=hashlib.sha256(data).hexdigest(),bytes_gz=len(data),
                 chk=dict(s_bn=s_bn,s_ti=s_ti,s_t=s_t,s_h=s_h,s_r=s_r,s_p=s_p,s_f=s_f,s_tr=s_tr),execution_id=ex,query_id=8907656,credits=cost)
        recs.append(rec); print(day,n,sv,rec['sha256_gz'])
    return recs
def compare_checksum(recs,chk_rows):
    R={r['d']:r for r in chk_rows}; bad=0; cells=0
    assert set(R)=={x['date'] for x in recs},('days differ',sorted(R),[x['date'] for x in recs])
    for x in recs:
        r=R[x['date']]
        for k,v in [('n',x['rows']),('sv',int(x['value_sum_atomic']))]+list(x['chk'].items()):
            cells+=1
            if int(r[k])!=int(v): bad+=1; print('DIFF',x['date'],k,r[k],v)
    print('checksum cells',cells,'diff',bad); return bad
def decode_s1a(files):
    """-> dict kind -> list of final CSV lines (a5 gets the upper-bound column)."""
    rows,total,ex,cost=load_files(files); assert len(rows)==total
    out={}
    for r in sorted(rows,key=lambda r:(r['kind'],r['d'])):
        ls=r['lines'].split('\n') if r['lines'] else []
        assert len(ls)==int(r['n']),('n',r['kind'],r['d'])
        if r['kind']=='a5': ls=[','.join(p[:2]+[str(EDGES[int(p[1])])]+p[2:]) for p in (l.split(',') for l in ls)]
        out.setdefault(r['kind'],[]).extend(ls)
    return out,ex,cost
HDRS={'a1':'date,settlements,recipients,payers,facilitators_active,value_atomic','a2':'date,facilitator,settlements,recipients,payers,value_atomic','a3':'date,recipient,settlements,value_atomic,payers','a4':'date,hour_utc,recipient,settlements,value_atomic','a5':'date,bucket,upper_bound_atomic_inclusive,settlements,value_atomic,max_value_atomic','a6':'date,events,tx_senders,txs,authorizers,events_from_20_facilitators,txs_from_20_facilitators','a7':'hour_utc,blocks,base_fee_p50_wei,base_fee_max_wei,base_fee_min_wei,base_fee_avg_wei'}
NAMES={'a1':'a1_daily','a2':'a2_daily_by_facilitator','a3':'a3_daily_by_recipient','a4':'a4_hourly_by_recipient','a5':'a5_daily_by_amount_bucket','a6':'a6_daily_authorization_events','a7':'a7_base_fee_hourly'}
