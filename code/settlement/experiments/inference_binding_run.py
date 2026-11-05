"""Open-weights execution-binding run: commit, re-execute, compare.

For each fixed prompt the script runs the honest seller path, verifies it, and
checks three fault cases against the same authenticated claims:
missing TOPLOC trace, int8 weight rounding under a float/bfloat16 commitment, and,
when --swap-model-dir is given, a different checkpoint declared under the claimed
model hash. It is a diagnostic, not a calibration or error-rate estimate.

Use --synthetic-seed instead of --model-dir for an offline run on a seeded random
checkpoint (see runtime/inference/model.py); that run says nothing about trained
model behaviour.
"""
import argparse, json, os, platform, subprocess, sys, tempfile, time
from pathlib import Path

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime' / 'inference'))
PROMPTS = ['A payment record identifies the request.', 'The seller publishes the committed response.',
           'A verifier compares reproducible evidence.']
SYNTHETIC_PROMPTS = [[1, 17, 300, 42, 901, 5, 77, 1203], [2, 9, 15, 2048, 3, 18, 400, 11, 64, 7],
                     [3, 4000, 31, 8, 250, 99]]

def main():
    p = argparse.ArgumentParser()
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument('--model-dir')
    src.add_argument('--synthetic-seed', type=int)
    p.add_argument('--swap-model-dir')
    p.add_argument('--output', required=True)
    p.add_argument('--precision', default='float32', choices=['float32', 'bfloat16'])
    p.add_argument('--max-new-tokens', type=int, default=16)
    p.add_argument('--threads', type=int, default=1)
    p.add_argument('--allow-dirty', action='store_true', help='for smoke tests only; the manifest records it')
    a = p.parse_args()
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    dirty = bool(git('status', '--porcelain'))
    if dirty and not a.allow_dirty:
        raise SystemExit('Clean checkout required')
    import torch
    import binding as B
    import model as M
    target = Path(a.output)
    target.mkdir(parents=True, exist_ok=False)
    scratch = tempfile.mkdtemp(prefix='fairbind-inference-')
    if a.synthetic_seed is not None:
        model_dir = M.write_synthetic_checkpoint(os.path.join(scratch, 'model'), a.synthetic_seed)
        swap_dir = M.write_synthetic_checkpoint(os.path.join(scratch, 'swap'), a.synthetic_seed + 1)
        prompts, tokenizer = [(None, ids) for ids in SYNTHETIC_PROMPTS], 'token-ids'
    else:
        from transformers import AutoTokenizer
        model_dir, swap_dir, tokenizer = a.model_dir, a.swap_model_dir, 'model-directory'
        tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
        prompts = [(text, tok(text)['input_ids']) for text in PROMPTS]
    config = B.config_manifest(tokenizer=tokenizer, precision=a.precision, max_new_tokens=a.max_new_tokens,
                               accelerator=B.accelerator_name(), threads=a.threads)
    limits, reason = B.check_config(config)
    if reason:
        raise SystemExit(reason)
    manifest_w = M.weight_manifest(model_dir)
    model_hash = B.hex32(B.object_hash(manifest_w))
    config_hash = B.hex32(B.keccak256(B.canonical(config)))
    claims = B.claims_object(model_hash, config_hash)
    report = {'revision': git('rev-parse', 'HEAD'), 'dirtyTree': dirty,
              'upstreams': json.loads((ROOT / 'UPSTREAMS.lock.json').read_text()),
              'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'model': 'synthetic seeded random checkpoint' if a.synthetic_seed is not None else 'local checkpoint',
              'syntheticSeed': a.synthetic_seed, 'weightManifest': manifest_w,
              'swapWeightManifest': M.weight_manifest(swap_dir) if swap_dir else None,
              'environment': {'python': sys.version, 'platform': platform.platform(), 'torch': torch.__version__,
                              'accelerator': B.accelerator_name()},
              'config': config, 'claims': claims, 'cases': []}
    for text, ids in prompts:
        start = time.perf_counter()
        honest = B.serve(model_dir, config, ids)
        serve_s = time.perf_counter() - start
        def check(served, **override):
            args = dict(claims=claims, preimage=served.preimage, config_bytes=honest.config_bytes,
                        trace_bytes=served.trace_bytes, model_dir=model_dir, prompt_ids=ids,
                        output_ids=served.output_ids, predicate_commitment=served.predicate_commitment)
            args.update(override)
            t0 = time.perf_counter()
            r = B.verify(**args)
            return {'verdict': r['verdict'], 'reason': r['reason'], 'metrics': r['metrics'],
                    'details': r['details'], 'verifySeconds': time.perf_counter() - t0}
        checks = {'exact_repeat': check(honest), 'missing_trace': check(honest, trace_bytes=None)}
        int8 = B.commit(M.load_model(model_dir, a.precision, 'int8-weight-rounding', 'eager', B._device(config)),
                        model_hash, config, ids)
        checks['int8_under_unquantized_claim'] = check(int8)
        if swap_dir:
            checks['swapped_model'] = check(B.commit(B.load_for(swap_dir, config), model_hash, config, ids))
        report['cases'].append({'prompt': text, 'inputIds': ids, 'outputIds': honest.output_ids,
                                'preimage': honest.preimage, 'predicateCommitment': honest.predicate_commitment,
                                'trace': json.loads(honest.trace_bytes), 'activationShapes': [list(x.shape) for x in honest.activations],
                                'activationsSha256': B.activation_digest(honest.activations),
                                'serveSeconds': serve_s, 'comparisons': checks})
    (target / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'revision': report['revision'], 'dirtyTree': dirty,
                      'cases': [{k: v['verdict'] for k, v in c['comparisons'].items()} for c in report['cases']]}, indent=2))

if __name__ == '__main__':
    main()
