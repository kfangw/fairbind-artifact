"""Run-level analysis only. Missing observations are errors, never zero or omitted."""
import argparse, hashlib, json, math, random, statistics, subprocess
from pathlib import Path

def wilson(successes, trials, z=1.959963984540054):
    if not isinstance(successes,int) or not isinstance(trials,int) or not 0<=successes<=trials or trials==0:
        raise ValueError('Use counts of independent trials, with a nonzero denominator')
    p=successes/trials;den=1+z*z/trials
    center=(p+z*z/(2*trials))/den
    half=z*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))/den
    return [max(0.,center-half),min(1.,center+half)]

def paired_runs(rows, left, right, *, repetitions=2000, seed=42):
    if left==right or repetitions<100:raise ValueError('Distinct methods and at least 100 resamples required')
    groups={}
    seen=set()
    for row in rows:
        if row['method'] not in (left,right):raise ValueError('Select an explicit method pair; extra methods are not discarded')
        key=(row['scenario'],row['run_id'],row['method'],row['observation_id'])
        if key in seen:raise ValueError('Duplicate observation')
        seen.add(key)
        value=row['value']
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Missing or nonfinite observation; report it before analysis')
        groups.setdefault(row['scenario'],{}).setdefault(row['run_id'],{}).setdefault(row['method'],[]).append(value)
    if not groups:raise ValueError('No observed data')
    result={};rng=random.Random(seed)
    for scenario,runs in sorted(groups.items()):
        if len(runs)<2:raise ValueError('At least two paired independent runs required')
        diffs=[];counts={}
        for rid,methods in sorted(runs.items()):
            if set(methods)!={left,right}:raise ValueError('Incomplete pair; do not drop failed or missing runs')
            diffs.append(statistics.mean(methods[left])-statistics.mean(methods[right]))
            counts[rid]={m:len(v) for m,v in methods.items()}
        boot=sorted(statistics.mean(rng.choices(diffs,k=len(diffs))) for _ in range(repetitions))
        def quantile(q):
            x=(len(boot)-1)*q;i=int(x);f=x-i
            return boot[i]*(1-f)+boot[min(i+1,len(boot)-1)]*f
        result[scenario]={'independent_runs':len(diffs),'observation_counts':counts,'mean_run_difference':statistics.mean(diffs),'percentile_95_interval':[quantile(.025),quantile(.975)]}
    return {'contrast':f'{left} minus {right}','aggregation':'equal weight per independent run; mean of observed metric within run','bootstrap_repetitions':repetitions,'seed':seed,'scenarios':result}

def main():
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('--left',required=True);p.add_argument('--right',required=True);p.add_argument('--seed',type=int,default=42);p.add_argument('--repetitions',type=int,default=2000);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():raise SystemExit('Clean checkout required')
    data=Path(a.input).read_bytes();rows=[json.loads(line) for line in data.splitlines() if line.strip()]
    out=paired_runs(rows,a.left,a.right,repetitions=a.repetitions,seed=a.seed)
    out.update(revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),input_sha256=hashlib.sha256(data).hexdigest())
    print(json.dumps(out,indent=2))
if __name__=='__main__':main()
