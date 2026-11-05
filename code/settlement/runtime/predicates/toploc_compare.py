"""TOPLOC comparison adapter; cryptographic purchase binding remains a worker duty.
The supplied tolerances are a fixed diagnostic or calibrated policy, never inferred
from the same results being classified. A comparison is not a protocol verdict.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Limits:
    max_exp_mismatches: int
    max_mantissa_mean: float
    max_mantissa_median: float

def compare(activations, proofs, *, topk, batch_size, limits):
    result={'verdict':'INCONCLUSIVE','reason':'','metrics':[]}
    if (not activations or topk<1 or batch_size<1 or not isinstance(limits.max_exp_mismatches,int)
        or limits.max_exp_mismatches<0 or limits.max_exp_mismatches>topk
        or any(not math.isfinite(v) or v<0 for v in [limits.max_mantissa_mean,limits.max_mantissa_median])):
        result['reason']='invalid input or limits';return result
    expected=1+(len(activations)-1+batch_size-1)//batch_size
    # Upstream pairs proofs and activation batches with zip; missing proofs must
    # not silently turn an incomplete comparison into PASS.
    if len(proofs)!=expected or any(not isinstance(p,bytes) or len(p)!=2+2*topk for p in proofs):
        result['reason']='missing or malformed proof blocks';return result
    if any(not 1<=int.from_bytes(p[:2],'big')<=65497 for p in proofs):
        result['reason']='null or invalid proof modulus';return result
    try:
        import torch
        from toploc import verify_proofs_bytes
    except (ImportError,OSError):
        result['reason']='TOPLOC runtime unavailable';return result
    if any(not isinstance(a,torch.Tensor) or a.dtype!=torch.bfloat16 or not bool(torch.isfinite(a).all()) for a in activations):
        result['reason']='unsupported activation encoding';return result
    try:
        # Preserve canonical prefill/decode blocks, but use the native verifier
        # for each flattened block; it applies the proof's index modulus.
        blocks=[activations[0].reshape(-1)]
        for i in range(1,len(activations),batch_size):
            blocks.append(torch.cat([v.reshape(-1) for v in activations[i:i+batch_size]]))
        rows=[]
        for block,proof in zip(blocks,proofs):
            if block.numel()<topk:raise ValueError('too few activation values')
            rows.extend(verify_proofs_bytes(block.reshape(1,-1).contiguous(),[proof],decode_batching_size=1,topk=topk,skip_prefill=True))
        if len(rows)!=expected:raise ValueError('incomplete comparison')
        result['metrics']=[{'exp_mismatches':r.exp_mismatches,'mantissa_mean':float(r.mant_err_mean),'mantissa_median':float(r.mant_err_median)} for r in rows]
        if any(not math.isfinite(v) or v<0 for row in result['metrics'] for v in row.values()):raise ValueError('invalid metric')
    except (ValueError,RuntimeError,IndexError,TypeError,AttributeError):
        result['reason']='comparison could not be established';return result
    failed=any(r['exp_mismatches']>limits.max_exp_mismatches or r['mantissa_mean']>limits.max_mantissa_mean or r['mantissa_median']>limits.max_mantissa_median for r in result['metrics'])
    result['verdict']='FAIL' if failed else 'PASS';result['reason']='fixed tolerance comparison';return result
