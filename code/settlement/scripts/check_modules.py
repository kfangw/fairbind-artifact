"""Compare module size limits, the recorded router ABI, and the shared storage layout after forge build."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def read(name):return json.loads((root/f'out/{name}.sol/{name}.json').read_text())
def wire(item):
    if isinstance(item,dict):return {k:wire(v) for k,v in item.items() if k not in ('internalType','name')}
    if isinstance(item,list):return [wire(v) for v in item]
    return item
before=json.loads((root/'test-vectors/deployment/monolith-abi.json').read_text())
after=read('FairBind')['abi']
for item in before:
    if item['type']=='constructor':continue
    assert any(item.get('name')==v.get('name') and wire(item)==wire(v) for v in after),item.get('name')
baseline=json.loads((root/'test-vectors/deployment/monolith-storage.json').read_text())
def layout_signature(layout):
    types=layout['types']
    def typ(key):
        t=types[key]
        # AST identifiers and source contract names are not part of storage encoding.
        out={k:t[k] for k in ('encoding','numberOfBytes')}
        if 'members' in t:out['members']=[field(v) for v in t['members']]
        for k in ('key','value','base'):
            if k in t:out[k]=typ(t[k])
        if not any(k in t for k in ('members','key','value','base')):out['label']=t['label'].replace('FairBindCore.','FairBind.')
        return out
    def field(v):return {'label':v['label'],'slot':v['slot'],'offset':v['offset'],'type':typ(v['type'])}
    return [field(v) for v in layout['storage']]
expected=layout_signature(baseline)
report={}
for name in ['FairBind','FairBindRegistry','FairBindSettlement','FairBindSampling','FairBindDelivery','FairBindPublication','FairBindRecovery','FairBindJudgment','FairBindReview','FairBindBond','FairBindLens','FairBindBatch','FairBindBatchAdmin','FairBindProof','FairBindDeposit','FairBindExchange','FairBindPassProof','FairBindSelfProof']:
    a=read(name)
    actual=layout_signature(a['storageLayout'])
    assert actual[:len(expected)]==expected,name+' original storage mismatch'
    assert actual==layout_signature(read('FairBind')['storageLayout']),name+' shared storage mismatch'
    runtime=len(a['deployedBytecode']['object'].removeprefix('0x'))//2
    initcode=len(a['bytecode']['object'].removeprefix('0x'))//2
    # Five addresses per module; router has five addresses plus ten module addresses.
    args=480 if name=='FairBind' else 160
    assert runtime<=24576,(name,runtime)
    assert initcode+args<=49152,(name,initcode+args)
    report[name]={'runtime_bytes':runtime,'initcode_with_constructor_bytes':initcode+args}
print(json.dumps({'original_abi':'preserved','original_storage':'original prefix preserved; shared append-only layout in all eighteen components','modules':report},indent=2))
