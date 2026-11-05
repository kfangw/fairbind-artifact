"""Test helper for pipeline_test.go: write a seeded synthetic checkpoint, run the
honest seller path and print the request/response bodies and commitment words.
Exits with status 3 when the torch, transformers and TOPLOC environment is absent.
"""
import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROMPT = [1, 17, 300, 42, 901, 5, 77, 1203, 64, 9]

def main():
    if not all(importlib.util.find_spec(n) for n in ('torch', 'transformers', 'toploc')):
        sys.exit(3)
    import binding as B
    import evaluate as E
    import model as M
    model_dir = M.write_synthetic_checkpoint(os.path.join(sys.argv[1], 'model'), 11)
    config = B.config_manifest(max_new_tokens=4)
    s = B.serve(model_dir, config, PROMPT)
    tampered = list(s.output_ids)
    tampered[1] = (tampered[1] + 1) % 4096
    enc = lambda b: base64.b64encode(b).decode()
    print(json.dumps({'modelDir': model_dir, 'config': enc(s.config_bytes), 'request': enc(E.request_body(PROMPT)),
                      'response': enc(E.response_body(s.output_ids, s.trace_bytes)),
                      'tamperedResponse': enc(E.response_body(tampered, s.trace_bytes)),
                      'preimage': s.preimage, 'predicateCommitment': s.predicate_commitment}))

if __name__ == '__main__':
    main()
