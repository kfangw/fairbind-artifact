"""Fixed CPU prefill diagnostic. Not a benchmark, calibration, or full predicate."""
import argparse, base64, hashlib, json, platform, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/predicates'))
from toploc_compare import Limits,compare

def main():
 p=argparse.ArgumentParser();p.add_argument('--model-dir',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 git=lambda *args:subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
 if git('status','--porcelain'):raise SystemExit('Clean checkout required')
 import torch,toploc,transformers
 from transformers import AutoTokenizer,AutoModelForCausalLM
 target=Path(a.output);target.mkdir(parents=True,exist_ok=False)
 model_dir=Path(a.model_dir)
 hashes={v.name:hashlib.sha256(v.read_bytes()).hexdigest() for v in model_dir.iterdir() if v.is_file()}
 torch.set_num_threads(1);torch.manual_seed(42);torch.use_deterministic_algorithms(True)
 tok=AutoTokenizer.from_pretrained(model_dir,local_files_only=True,trust_remote_code=False)
 model=AutoModelForCausalLM.from_pretrained(model_dir,local_files_only=True,trust_remote_code=False,use_safetensors=True,torch_dtype=torch.float32,attn_implementation='eager').eval()
 report={'revision':git('rev-parse','HEAD'),'upstreams':json.loads((ROOT/'UPSTREAMS.lock.json').read_text()),'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'grade':'G','scope':'CPU prefill and comparison diagnostic only; three fixed prompts; no error-rate estimate','environment':{'python':sys.version,'platform':platform.platform(),'torch':torch.__version__,'toploc':toploc.__version__,'transformers':transformers.__version__},'model_files_sha256':hashes,'configuration':{'seed':42,'threads':1,'model_dtype':'float32','proof_activation_dtype':'bfloat16','layer':'final hidden state','topk':16,'decode_batching_size':8,'skip_prefill':False,'limits':{'max_exp_mismatches':0,'max_mantissa_mean':0,'max_mantissa_median':0},'policy_status':'exact-repeat diagnostic, not cross-hardware calibration'},'cases':[]}
 prompts=['A payment record identifies the request.','The seller publishes the committed response.','A verifier compares reproducible evidence.']
 with torch.inference_mode():
  for i,prompt in enumerate(prompts):
   ids=tok(prompt,return_tensors='pt')['input_ids']
   def prefill(tokens):
    start=time.perf_counter();out=model(input_ids=tokens,output_hidden_states=True,use_cache=False)
    return out.hidden_states[-1][0].to(torch.bfloat16).contiguous(),time.perf_counter()-start
   source,t_source=prefill(ids);reference,t_reference=prefill(ids)
   # Same-length changed input is a diagnostic attack, not a realistic workload estimate.
   changed=(ids+1)%model.config.vocab_size;wrong,t_wrong=prefill(changed)
   proofs=toploc.build_proofs_bytes([source],decode_batching_size=8,topk=16,skip_prefill=False)
   checks={}
   for name,acts,ps in [('exact_repeat',[reference],proofs),('changed_input',[wrong],proofs),('missing_proof',[reference],[])]:
    start=time.perf_counter();checks[name]=compare(acts,ps,topk=16,batch_size=8,limits=Limits(0,0,0));checks[name]['comparison_seconds']=time.perf_counter()-start
   files={}
   for name,tensor in [('source',source),('reference',reference),('changed',wrong)]:
    data=tensor.view(torch.uint16).numpy().tobytes();filename=f'{i}-{name}.bf16';(target/filename).write_bytes(data);files[name]={'file':filename,'shape':list(tensor.shape),'byteorder':sys.byteorder,'sha256':hashlib.sha256(data).hexdigest()}
   report['cases'].append({'prompt':prompt,'input_ids':ids.tolist(),'changed_input_ids':changed.tolist(),'prefill_seconds':{'source':t_source,'reference':t_reference,'changed':t_wrong},'proofs_base64':[base64.b64encode(v).decode() for v in proofs],'activations':files,'comparisons':checks})
   assert checks['exact_repeat']['verdict']=='PASS','deterministic repeat failed'
   assert checks['missing_proof']['verdict']=='INCONCLUSIVE','missing proof accepted'
 (target/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'revision':report['revision'],'cases':[{k:v['verdict'] for k,v in c['comparisons'].items()} for c in report['cases']]},indent=2))
if __name__=='__main__':main()
