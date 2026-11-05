"""Deploy artifacts on an owned ephemeral Anvil, with normal code size limits.
No remote RPC or private key input is accepted. Run after committing the build inputs.
With --rpc-url the script attaches to an Anvil already running on a loopback
address (scripts/deploy-local.sh) and leaves it running.
"""
import argparse, hashlib, ipaddress, json, os, socket, subprocess, tempfile, time, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NAMES=['FairBindRegistry','FairBindSettlement','FairBindSampling','FairBindDelivery','FairBindPublication','FairBindRecovery','FairBindJudgment','FairBindReview','FairBindBond','FairBindLens']
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True)
    # Test build for deferral sweeps: registry module from contracts/test/AdmissionOverrideRegistry.sol.
    ap.add_argument('--admission-override',action='store_true',help='deploy the admission override test build')
    ap.add_argument('--profile',help='derived profile document; its admissionOverride flag selects the test build')
    ap.add_argument('--rpc-url',help='attach to this loopback Anvil instead of starting one')
    ap.add_argument('--allow-dirty',action='store_true',help='deploy from a dirty tree; recorded as dirty in the report')
    a=ap.parse_args()
    override=a.admission_override or os.environ.get('FAIRBIND_ADMISSION_OVERRIDE')=='1'
    if a.profile:override=override or json.loads(Path(a.profile).read_text()).get('admissionOverride') is True
    anvil=os.environ.get('FAIRBIND_ANVIL') or 'anvil'
    names=[('AdmissionOverrideRegistry' if override and n=='FairBindRegistry' else n) for n in NAMES]
    git=lambda *args:subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
    dirty=bool(git('status','--porcelain'))
    if dirty and not a.allow_dirty:raise SystemExit('Clean checkout required')
    if a.rpc_url:
        u=urllib.parse.urlparse(a.rpc_url)
        try:loopback=u.scheme=='http' and ipaddress.ip_address(u.hostname or '').is_loopback
        except ValueError:loopback=False
        if not loopback:raise SystemExit('--rpc-url must be a literal loopback http URL')
        url=a.rpc_url.rstrip('/')
    else:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
    def rpc(method,params):
        req=urllib.request.Request(url,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),{'Content-Type':'application/json'})
        result=json.load(urllib.request.urlopen(req,timeout=10))
        if 'error' in result:raise RuntimeError(result['error'])
        return result['result']
    with tempfile.TemporaryFile() as logs:
        proc=None if a.rpc_url else subprocess.Popen([anvil,'--host','127.0.0.1','--port',str(port),'--chain-id','31337','--silent'],stdout=logs,stderr=logs)
        try:
            for _ in range(100):
                try:accounts=rpc('eth_accounts',[]);break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('Anvil did not start')
            chain_id=int(rpc('eth_chainId',[]),16)
            report={'commit':git('rev-parse','HEAD'),'dirty':dirty,'rpc_url':url,'attached':bool(a.rpc_url),'upstreams':json.loads((ROOT/'UPSTREAMS.lock.json').read_text()),'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'chain_id':chain_id,'seed':'Anvil default deterministic accounts','anvil':subprocess.check_output([anvil,'--version'],text=True).strip(),'forge':subprocess.check_output(['forge','--version'],text=True).strip(),'scope':'Local deployment only; mock token; normal EIP-170/EIP-3860 limits','admission_override':override,'build':'test: admission override registry' if override else 'production','deployments':{}}
            def deploy(name,args):
                artifact=json.loads((ROOT/f'out/{name}.sol/{name}.json').read_text())
                code=artifact['bytecode']['object'].removeprefix('0x')
                data='0x'+code+''.join(v.removeprefix('0x').zfill(64) for v in args)
                assert len(data[2:])//2<=49152
                tx=rpc('eth_sendTransaction',[{'from':accounts[0],'data':data,'gas':hex(15_000_000)}])
                for _ in range(100):
                    rec=rpc('eth_getTransactionReceipt',[tx])
                    if rec:break
                    time.sleep(.1)
                assert rec and int(rec['status'],16)==1,(name,rec)
                addr=rec['contractAddress'];actual=rpc('eth_getCode',[addr,'latest'])
                built=bytearray.fromhex(artifact['deployedBytecode']['object'].removeprefix('0x'))
                normalized=bytearray.fromhex(actual[2:]);assert len(normalized)<=24576
                for ranges in artifact['deployedBytecode'].get('immutableReferences',{}).values():
                    for pos in ranges:
                        start=pos['start'];end=start+pos['length'];built[start:end]=b'\0'*(end-start);normalized[start:end]=b'\0'*(end-start)
                assert built==normalized, name+' artifact mismatch'
                report['deployments'][name]={'address':addr,'transaction':tx,'gas_used':int(rec['gasUsed'],16),'runtime_bytes':len(normalized),'initcode_with_args_bytes':len(data[2:])//2,'code_keccak256':rpc('web3_sha3',[actual]),'artifact_sha256':hashlib.sha256((ROOT/f'out/{name}.sol/{name}.json').read_bytes()).hexdigest(),'artifact_code_match_excluding_immutables':True}
                return addr
            token=deploy('MockEIP3009Token',[])
            args=[token,accounts[0],accounts[1],accounts[2],accounts[3]]
            modules=[deploy(n,args) for n in names]
            router=deploy('FairBind',args+modules)
            def get(addr,signature):
                selector=rpc('web3_sha3',['0x'+signature.encode().hex()])[:10]
                return rpc('eth_call',[{'to':addr,'data':selector},'latest'])
            for i,(name,addr) in enumerate(zip(NAMES,modules)):
                assert int(get(addr,'MODULE_KIND()'),16)==i+1
                assert get(addr,'deploymentToken()')[-40:]==token[2:]
                assert get(addr,'penaltyTreasury()')[-40:]==accounts[2][2:]
                assert get(addr,'verifierRewardPool()')[-40:]==accounts[3][2:]
                getter=name.removeprefix('FairBind').lower()+'Module()'
                assert get(router,getter)[-40:]==addr[2:]
            report['configuration_checks']='passed';report['total_gas']=sum(v['gas_used'] for v in report['deployments'].values())
            report['roles']={'governance':accounts[0],'guardian':accounts[1],'penalty_treasury':accounts[2],'verifier_reward_pool':accounts[3]}
            report['token']=token;report['router']=router
            Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        finally:
            if proc is not None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
if __name__=='__main__':main()
